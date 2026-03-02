import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional
from urllib.request import Request, urlopen

from tts_client import merge_wavs, split_sentences, synthesize_wav

DEFAULT_OUTPUT = os.path.join("Nachrichten", "Aktuell.mp3")
DEFAULT_MODEL_DIR = "/mnt/tts/models/thorsten"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_NEWS_SOURCE = "tagesschau"

TAGESSCHAU_FEEDS = {
    "all": "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml",
    "inland": "https://www.tagesschau.de/inland/index~rss2.xml",
    "europa": "https://www.tagesschau.de/ausland/europa/index~rss2.xml",
    "ausland": "https://www.tagesschau.de/ausland/index~rss2.xml",
    "wissen": "https://www.tagesschau.de/wissen/index~rss2.xml",
    "wetter": "https://www.tagesschau.de/wetter/index~rss2.xml",
    "sport": "https://www.sportschau.de/index~rss2.xml",
}

VOICE_OPTIONS = {
    "neutral": {
        "label": "Thorsten High",
        "model": "de_DE-thorsten-high.onnx",
        "config": "de_DE-thorsten-high.onnx.json",
        "supports_emotion": False,
    },
    "emotional": {
        "label": "Thorsten Emotional",
        "model": "de_DE-thorsten_emotional-medium.onnx",
        "config": "de_DE-thorsten_emotional-medium.onnx.json",
        "supports_emotion": True,
    },
    "hessisch": {
        "label": "Thorsten Hessisch",
        "model": "de_DE-thorsten_hessisch-medium.onnx",
        "config": "de_DE-thorsten_hessisch-medium.onnx.json",
        "supports_emotion": False,
    },
}

EMOTION_SPEAKERS = {
    "happy": 0,
    "angry": 1,
    "disgusted": 2,
    "drunk": 3,
    "neutral": 4,
    "sleepy": 5,
    "surprised": 6,
    "whisper": 7,
}


DEFAULT_PROMPT = (
    "Schreibe einen kurzen Nachrichtenueberblick auf Deutsch (max. 1200 Zeichen). "
    "Strukturiere ihn in 3-5 knappen Meldungen mit kurzen Ueberschriften. "
    "Kein Quellenverweis, keine Aufzaehlungszeichen mit Zahlen. "
    "Beende mit einem kurzen Ausblick-Satz."
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

FeedItem = Dict[str, str]


def load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[len("export ") :].strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def resolve_voice(voice_key: str) -> dict:
    if isinstance(voice_key, str):
        option = VOICE_OPTIONS.get(voice_key.strip().lower())
        if option:
            return option
    return VOICE_OPTIONS["neutral"]


def resolve_emotion(emotion_value: Optional[str]) -> int:
    if emotion_value is None:
        return EMOTION_SPEAKERS["neutral"]
    cleaned = str(emotion_value).strip().lower()
    if cleaned.isdigit():
        num = int(cleaned)
        if num in EMOTION_SPEAKERS.values():
            return num
        raise ValueError("emotion speaker id is invalid")
    if cleaned in EMOTION_SPEAKERS:
        return EMOTION_SPEAKERS[cleaned]
    raise ValueError("emotion must be a known key or speaker id")


def build_prompt(custom_prompt: Optional[str]) -> str:
    today = date.today().strftime("%d.%m.%Y")
    base = custom_prompt.strip() if custom_prompt else DEFAULT_PROMPT
    return f"Stand: {today}. {base}"


def _next_full_hour(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now().astimezone()
    floored = now.replace(minute=0, second=0, microsecond=0)
    if now == floored:
        return floored
    return floored + timedelta(hours=1)


def _day_ordinal_word(day: int) -> str:
    words = {
        1: "erste",
        2: "zweite",
        3: "dritte",
        4: "vierte",
        5: "fuenfte",
        6: "sechste",
        7: "siebte",
        8: "achte",
        9: "neunte",
        10: "zehnte",
        11: "elfte",
        12: "zwoelfte",
        13: "dreizehnte",
        14: "vierzehnte",
        15: "fuenfzehnte",
        16: "sechzehnte",
        17: "siebzehnte",
        18: "achtzehnte",
        19: "neunzehnte",
        20: "zwanzigste",
        21: "einundzwanzigste",
        22: "zweiundzwanzigste",
        23: "dreiundzwanzigste",
        24: "vierundzwanzigste",
        25: "fuenfundzwanzigste",
        26: "sechsundzwanzigste",
        27: "siebenundzwanzigste",
        28: "achtundzwanzigste",
        29: "neunundzwanzigste",
        30: "dreissigste",
        31: "einunddreissigste",
    }
    return words.get(day, f"{day}.")


def _build_intro_text(now: Optional[datetime] = None) -> str:
    target = _next_full_hour(now)
    weekdays = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    months = [
        "Januar",
        "Februar",
        "Maerz",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    weekday = weekdays[target.weekday()]
    month = months[target.month - 1]
    day_word = _day_ordinal_word(target.day)
    return (
        "Und hier die AI-Radio Nachrichten zur vollen Stunde. "
        f"Es ist {weekday}, der {day_word} {month} {target.year} um {target.hour} Uhr."
    )


def _build_outro_text() -> str:
    return (
        "Diese Nachrichten wurden dem Newsfeed der Tagesschau entnommen und "
        "von Thorsten TTS gesprochen. Alles wie gewohnt automatisch von AI-Radio."
    )


def fetch_news_text(api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "developer", "content": "Du bist ein praeziser deutscher Nachrichtenredakteur."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("OpenAI response did not include content")
    return content


def _http_get_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "ThorstenTTS/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        curl_bin = shutil.which("curl")
        if curl_bin is None:
            raise RuntimeError(f"Failed to fetch URL and curl not available: {url}") from exc
        proc = subprocess.run(
            [curl_bin, "-fsSL", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or "unknown curl error"
            raise RuntimeError(f"Failed to fetch URL: {url} ({err})") from exc
        return proc.stdout


def _clean_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text).strip()
    text = re.sub(r"\[\s*mehr\s*\]$", "", text, flags=re.IGNORECASE).strip()
    return text


def _shorten(text: str, max_chars: int) -> str:
    cleaned = _WS_RE.sub(" ", text).strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    # Nicht mitten im Satz kuerzen, damit Thorsten vollstaendige Saetze spricht.
    split = max(cleaned.rfind(".", 0, max_chars), cleaned.rfind("!", 0, max_chars), cleaned.rfind("?", 0, max_chars))
    if split >= int(max_chars * 0.6):
        return cleaned[: split + 1].strip()
    return cleaned


def _strip_byline(text: str) -> str:
    return re.sub(r"\s+Von\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\- ]+$", "", text).strip()


def _parse_rss_items(xml_text: str, max_items: int = 50) -> List[FeedItem]:
    root = ET.fromstring(xml_text)
    items: List[FeedItem] = []
    for node in root.findall("./channel/item"):
        title = _clean_text(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        description = _clean_text(node.findtext("description") or "")
        pub_date = _clean_text(node.findtext("pubDate") or "")
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pubDate": pub_date,
            }
        )
        if len(items) >= max_items:
            break
    return items


def fetch_rss_items(url: str, max_items: int = 50) -> List[FeedItem]:
    xml_text = _http_get_text(url, timeout=25)
    return _parse_rss_items(xml_text, max_items=max_items)


def _pick_items(
    source: List[FeedItem],
    count: int,
    used_links: set[str],
    predicate: Optional[Callable[[FeedItem], bool]] = None,
) -> List[FeedItem]:
    selected: List[FeedItem] = []
    for item in source:
        link = item.get("link", "")
        if not link or link in used_links:
            continue
        if predicate and not predicate(item):
            continue
        selected.append(item)
        used_links.add(link)
        if len(selected) >= count:
            break
    return selected


def _fill_with_fallback(
    selected: List[FeedItem],
    target: int,
    used_links: set[str],
    pools: List[List[FeedItem]],
    predicate: Optional[Callable[[FeedItem], bool]] = None,
) -> List[FeedItem]:
    if len(selected) >= target:
        return selected
    needed = target - len(selected)
    for pool in pools:
        for item in pool:
            link = item.get("link", "")
            if not link or link in used_links:
                continue
            if predicate and not predicate(item):
                continue
            selected.append(item)
            used_links.add(link)
            needed -= 1
            if needed <= 0:
                return selected
    return selected


def _render_item(item: FeedItem, max_chars: int = 260) -> str:
    title = _clean_text(item.get("title", "")).rstrip(".")
    desc = _strip_byline(_clean_text(item.get("description", "")))
    if desc and desc.lower().startswith(title.lower()):
        desc = ""
    if desc:
        sep = " " if title.endswith(("?", "!", ".", ":")) else ". "
        text = f"{title}{sep}{desc}"
    else:
        text = title
    return _shorten(text, max_chars=max_chars)


def _render_weather_item(item: FeedItem, max_chars: int = 240) -> str:
    title = _clean_text(item.get("title", ""))
    title = re.sub(r"(?i)^wetter\s*(deutschland|vorhersage deutschland|vorhersage europa|europa|welt)?\s*:?\s*", "", title).strip()
    desc = _strip_byline(_clean_text(item.get("description", "")))
    text = desc or title
    return _shorten(text, max_chars=max_chars)


def _select_curious_item(
    used_links: set[str],
    primary_pool: List[FeedItem],
    fallback_pool: List[FeedItem],
) -> Optional[FeedItem]:
    positive = (
        "kurios",
        "skurril",
        "ungewoehnlich",
        "ungewoehnliche",
        "rekord",
        "tier",
        "verblueffend",
        "entdeckt",
        "sensation",
        "witz",
        "humor",
        "impression",
    )
    negative = (
        "krieg",
        "angriff",
        "bomb",
        "regierung",
        "kanzler",
        "wahl",
        "konflikt",
        "toete",
        "verletz",
        "nahost",
        "iran",
        "israel",
        "ukraine",
        "russland",
    )

    best_item: Optional[FeedItem] = None
    best_score = -10_000
    for pool in (primary_pool, fallback_pool):
        for item in pool:
            link = item.get("link", "")
            if not link or link in used_links:
                continue
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            score = 0
            if any(word in haystack for word in positive):
                score += 8
            if "/wissen/" in link or "/multimedia/" in link or "/wetter/" in link:
                score += 5
            if "/inland/" in link or "/ausland/" in link:
                score -= 2
            if any(word in haystack for word in negative):
                score -= 10
            if score > best_score:
                best_score = score
                best_item = item

    if best_item and best_score > 0:
        used_links.add(best_item.get("link", ""))
        return best_item
    return None


def _safe_fetch_feed(name: str) -> List[FeedItem]:
    url = TAGESSCHAU_FEEDS[name]
    try:
        return fetch_rss_items(url, max_items=60)
    except Exception:
        return []


def build_tagesschau_news_text(sport_items: int = 2) -> str:
    all_items = _safe_fetch_feed("all")
    inland_items = _safe_fetch_feed("inland")
    europa_items = _safe_fetch_feed("europa")
    ausland_items = _safe_fetch_feed("ausland")
    wissen_items = _safe_fetch_feed("wissen")
    wetter_items = _safe_fetch_feed("wetter")
    sport_feed_items = _safe_fetch_feed("sport")

    if not all_items:
        raise RuntimeError("Tagesschau-Feed konnte nicht geladen werden")

    used_links: set[str] = set()

    top_theme = _pick_items(all_items, 2, used_links)

    deutschland = _pick_items(inland_items, 3, used_links)
    deutschland = _fill_with_fallback(
        deutschland,
        3,
        used_links,
        [all_items],
        predicate=lambda it: "/inland/" in it.get("link", ""),
    )

    europa = _pick_items(europa_items, 3, used_links)
    europa = _fill_with_fallback(
        europa,
        3,
        used_links,
        [all_items, ausland_items],
        predicate=lambda it: "/ausland/europa/" in it.get("link", ""),
    )

    welt = _pick_items(
        ausland_items,
        3,
        used_links,
        predicate=lambda it: "/ausland/europa/" not in it.get("link", ""),
    )
    welt = _fill_with_fallback(
        welt,
        3,
        used_links,
        [all_items],
        predicate=lambda it: "/ausland/" in it.get("link", "") and "/ausland/europa/" not in it.get("link", ""),
    )

    sport_count = min(max(int(sport_items), 1), 2)
    sport = _pick_items(sport_feed_items, sport_count, used_links)
    if not sport:
        sport = _pick_items(
            all_items,
            sport_count,
            used_links,
            predicate=lambda it: "/sport/" in it.get("link", ""),
        )

    curious = _select_curious_item(used_links, all_items, wissen_items)

    wetter_de = _pick_items(
        wetter_items,
        1,
        used_links,
        predicate=lambda it: "/wetter/deutschland/" in it.get("link", ""),
    )
    if not wetter_de:
        wetter_de = _pick_items(wetter_items, 1, used_links)

    def section(title: str, items: List[FeedItem], max_chars: int = 0) -> List[str]:
        lines = [title]
        if not items:
            lines.append("- Keine passende aktuelle Meldung im Feed gefunden.")
            return lines
        for item in items:
            lines.append(f"- {_render_item(item, max_chars=max_chars)}")
        return lines

    lines: List[str] = []
    lines.append(_build_intro_text())
    lines.append("")
    lines.extend(section("TOP-THEMA", top_theme))
    lines.append("")
    lines.extend(section("DEUTSCHLAND", deutschland))
    lines.append("")
    lines.extend(section("EUROPA", europa))
    lines.append("")
    lines.extend(section("WELT", welt))
    lines.append("")
    lines.extend(section("SPORT", sport))
    lines.append("")
    lines.append("KURIOSES")
    if curious:
        lines.append(f"- {_render_item(curious, max_chars=0)}")
    else:
        lines.append("- Keine passende kuriose Meldung im Feed gefunden.")
    lines.append("")
    lines.append("WETTER")
    if wetter_de:
        lines.append(f"- {_render_weather_item(wetter_de[0], max_chars=0)}")
    else:
        lines.append("- Keine aktuelle Wetter-Meldung im Feed gefunden.")
    lines.append("")
    lines.append(_build_outro_text())

    return "\n".join(lines).strip()


def wav_to_mp3(wav_bytes: bytes, text: str) -> bytes:
    wav_path = None
    mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = wav_file.name
            wav_file.write(wav_bytes)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as mp3_file:
            mp3_path = mp3_file.name
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            wav_path,
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "3",
            "-metadata",
            f"lyrics={text}",
            mp3_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed: {err}")
        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate news text and synthesize MP3 with Thorsten")
    parser.add_argument("--pi-host", required=True, help="Pi host (e.g. pi5)")
    parser.add_argument("--pi-user", required=True, help="SSH user (e.g. pi)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output MP3 path")
    parser.add_argument("--voice", default="neutral", choices=VOICE_OPTIONS.keys(), help="Voice preset")
    parser.add_argument("--emotion", default="neutral", help="Emotion for emotional voice")
    parser.add_argument("--model-dir", default=None, help=f"Piper model directory (default: {DEFAULT_MODEL_DIR})")
    parser.add_argument("--openai-model", default=None, help=f"OpenAI model (default: {DEFAULT_OPENAI_MODEL})")
    parser.add_argument("--prompt", default=None, help="Custom OpenAI prompt")
    parser.add_argument(
        "--source",
        choices=["tagesschau", "openai"],
        default=None,
        help="News source: 'tagesschau' (RSS) or 'openai' (model-generated)",
    )
    parser.add_argument("--sport-items", type=int, default=2, help="Number of sport items (1-2)")
    parser.add_argument("--text-only", action="store_true", help="Print text only, do not generate MP3")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.getcwd(), ".env"))

    source = (args.source or os.environ.get("NEWS_SOURCE", DEFAULT_NEWS_SOURCE)).strip().lower()
    model_dir = args.model_dir or os.environ.get("TTS_MODEL_DIR", DEFAULT_MODEL_DIR)
    openai_model = args.openai_model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    prompt = args.prompt if args.prompt is not None else os.environ.get("NEWS_PROMPT")

    voice = resolve_voice(args.voice)
    speaker = None
    if voice["supports_emotion"]:
        speaker = resolve_emotion(args.emotion)

    model_path = os.path.join(model_dir, voice["model"])
    config_path = os.path.join(model_dir, voice["config"])

    if source == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY missing. Put it in .env or environment.")
        user_prompt = build_prompt(prompt)
        text = fetch_news_text(api_key, openai_model, user_prompt)
    else:
        text = build_tagesschau_news_text(sport_items=args.sport_items)

    if args.text_only:
        print(text)
        return 0

    sentences = split_sentences(text)
    if not sentences:
        raise SystemExit("News text is empty")

    wavs = [
        synthesize_wav(sentence, args.pi_host, args.pi_user, model_path, config_path, speaker)
        for sentence in sentences
    ]
    merged = merge_wavs(wavs)
    mp3_bytes = wav_to_mp3(merged, text)

    out_path = os.path.abspath(args.output)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(mp3_bytes)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
