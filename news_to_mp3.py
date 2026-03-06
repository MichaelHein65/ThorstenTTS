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
from email.utils import parsedate_to_datetime
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

SECTION_ORDER = ["TOP-THEMA", "DEUTSCHLAND", "EUROPA", "WELT", "SPORT", "KURIOSES", "WETTER"]
SECTION_TARGET_COUNTS = {
    "TOP-THEMA": 2,
    "DEUTSCHLAND": 3,
    "EUROPA": 3,
    "WELT": 3,
    "SPORT": 2,
    "KURIOSES": 1,
    "WETTER": 1,
}

NOISE_KEYWORDS = (
    "podcast",
    "wintersport-podcast",
    "folge",
    "episode",
    "livestream",
    "liveblog",
    "ticker",
    "newsletter",
    "schreibt uns",
    "feedback",
    "mail an",
    "@",
    "video",
    "audio",
    "mediathek",
)

CURIOUS_NEGATIVE_KEYWORDS = (
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

CURIOUS_POSITIVE_KEYWORDS = (
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
)

CURIOUS_REPEAT_BLOCK_HOURS = 72
CURIOUS_HISTORY_KEEP_DAYS = 14


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
        f"Es ist {weekday}, der {day_word} {month} {target.year}."
    )


def _build_outro_text() -> str:
    return (
        "Diese Nachrichten wurden dem Newsfeed der Tagesschau entnommen und "
        "von Thorsten TTS gesprochen. Alles wie gewohnt automatisch von AI-Radio."
    )


def _openai_chat_completion(
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    response_format: Optional[Dict[str, str]] = None,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    payload_json = json.dumps(payload)
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload_json.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except Exception as exc:
        curl_bin = shutil.which("curl")
        if curl_bin is None:
            raise
        proc = subprocess.run(
            [
                curl_bin,
                "-fsSL",
                "https://api.openai.com/v1/chat/completions",
                "-H",
                "Content-Type: application/json",
                "-H",
                f"Authorization: Bearer {api_key}",
                "-d",
                payload_json,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or "unknown curl error"
            raise RuntimeError(f"OpenAI request failed ({err})") from exc
        raw = proc.stdout.encode("utf-8")
    data = json.loads(raw.decode("utf-8"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("OpenAI response did not include content")
    return content


def fetch_news_text(api_key: str, model: str, prompt: str) -> str:
    return _openai_chat_completion(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "developer", "content": "Du bist ein praeziser deutscher Nachrichtenredakteur."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )


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


def _parse_pub_date(item: FeedItem) -> Optional[datetime]:
    raw = item.get("pubDate", "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone()


def _is_recent_item(item: FeedItem, max_age_hours: int) -> bool:
    dt = _parse_pub_date(item)
    if dt is None:
        return True
    age = datetime.now().astimezone() - dt
    return age <= timedelta(hours=max_age_hours)


def _is_noise_item(item: FeedItem) -> bool:
    title = _clean_text(item.get("title", "")).lower()
    desc = _clean_text(item.get("description", "")).lower()
    link = item.get("link", "").lower()
    haystack = f"{title} {desc} {link}"
    if any(term in haystack for term in NOISE_KEYWORDS):
        return True
    return False


def _filter_items(items: List[FeedItem], max_desc_chars: int = 380) -> List[FeedItem]:
    filtered: List[FeedItem] = []
    for item in items:
        if _is_noise_item(item):
            continue
        desc = _clean_text(item.get("description", ""))
        if len(desc) > max_desc_chars:
            continue
        filtered.append(item)
    return filtered


def _extract_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _compose_body_from_sections(section_lines: Dict[str, List[str]]) -> str:
    def split_sentence_parts(text: str) -> List[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]

    def ensure_min_sentences(section: str, bullet_text: str, minimum: int = 3) -> str:
        text = _clean_text(bullet_text)
        if text and text[-1] not in ".!?":
            text = text + "."
        parts = split_sentence_parts(text)
        fillers_by_section = {
            "WETTER": [
                "Regional sind dabei weiterhin Unterschiede moeglich.",
                "Im Tagesverlauf bleibt die Lage unter Beobachtung.",
            ],
            "KURIOSES": [
                "Das Thema sorgt weiter fuer Aufmerksamkeit.",
                "Weitere Entwicklungen werden zeitnah erwartet.",
            ],
        }
        default_fillers = [
            "Die Entwicklung wird weiter beobachtet.",
            "Weitere Details werden im Tagesverlauf erwartet.",
        ]
        fillers = fillers_by_section.get(section, default_fillers)
        idx = 0
        while len(parts) < minimum:
            parts.append(fillers[min(idx, len(fillers) - 1)])
            idx += 1
        return " ".join(parts)

    def fallback_line(section: str) -> str:
        if section == "KURIOSES":
            return "Heute liegt keine passende kuriose Meldung vor."
        if section == "WETTER":
            return "Zum Wetter liegt aktuell keine kompakte Deutschland-Meldung vor."
        if section == "SPORT":
            return "Keine weitere passende aktuelle Sportmeldung im Feed gefunden."
        return "Keine weitere passende aktuelle Meldung im Feed gefunden."

    lines: List[str] = []
    for section in SECTION_ORDER:
        lines.append(section)
        bullets = [line.strip() for line in section_lines.get(section, []) if line.strip()]
        target_count = SECTION_TARGET_COUNTS[section]
        while len(bullets) < target_count:
            bullets.append(fallback_line(section))
        for bullet in bullets:
            bullet_text = bullet[2:].strip() if bullet.startswith("- ") else bullet
            bullet_text = ensure_min_sentences(section, bullet_text, minimum=3)
            lines.append(f"- {bullet_text}")
        lines.append("")
    return "\n".join(lines).strip()


def _validate_broadcast_body(text: str) -> bool:
    if not text.strip():
        return False
    if len(text) > 9000:
        return False
    lowered = text.lower()
    banned = ("schreibt uns", "feedback", "podcast", "newsletter", "@")
    if any(term in lowered for term in banned):
        return False
    lines = [line.rstrip() for line in text.splitlines()]
    sections_seen = []
    current = None
    bullet_count = 0
    section_counts: Dict[str, int] = {name: 0 for name in SECTION_ORDER}
    for line in lines:
        if not line:
            continue
        if line in SECTION_ORDER:
            sections_seen.append(line)
            current = line
            continue
        if line.startswith("- "):
            if current is None:
                return False
            bullet_count += 1
            section_counts[current] += 1
            if len(line) > 850:
                return False
            sentence_count = len([p for p in re.split(r"(?<=[.!?])\s+", line[2:].strip()) if p.strip()])
            if sentence_count < 3:
                return False
            continue
        return False
    if sections_seen != SECTION_ORDER:
        return False
    for section in SECTION_ORDER:
        if section_counts[section] < SECTION_TARGET_COUNTS[section]:
            return False
    return bullet_count >= sum(SECTION_TARGET_COUNTS.values())


def _redact_items_with_openai(
    api_key: str,
    model: str,
    items_by_id: Dict[str, str],
) -> Dict[str, str]:
    payload_items = [{"id": item_id, "text": text} for item_id, text in items_by_id.items()]
    user_payload = {"items": payload_items}
    prompt = (
        "Redigiere jede Meldung in neutrales, knappes Nachrichtenradio-Deutsch. "
        "Regeln: mindestens drei Saetze pro Meldung, maximal 700 Zeichen, keine Calls-to-Action, "
        "keine Quellenhinweise, keine Autoren, keine E-Mail-Adressen. "
        "Bedeutung erhalten, nichts hinzuerfinden. "
        "Antworte NUR als JSON: {\"items\":[{\"id\":\"...\",\"text\":\"...\"}]}. "
        f"Eingabe: {json.dumps(user_payload, ensure_ascii=False)}"
    )
    raw = _openai_chat_completion(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "developer", "content": "Du redigierst RSS-Meldungen fuer ein deutsches Nachrichtenradio."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    parsed = _extract_json_object(raw)
    result: Dict[str, str] = {}
    for entry in parsed.get("items", []):
        item_id = str(entry.get("id", "")).strip()
        text = _clean_text(str(entry.get("text", "")).strip())
        if not item_id or not text:
            continue
        result[item_id] = _shorten(text, max_chars=700)
    return result


def _polish_body_with_openai(api_key: str, model: str, body: str) -> str:
    prompt = (
        "Ueberarbeite den folgenden Nachrichtentext fuer stuedliche Audio-Ausstrahlung. "
        "Regeln strikt einhalten: "
        "1) Behalte exakt diese Ueberschriften und Reihenfolge: TOP-THEMA, DEUTSCHLAND, EUROPA, WELT, SPORT, KURIOSES, WETTER. "
        "2) Unter jeder Ueberschrift nur Aufzaehlungszeilen mit '- '. "
        "3) Anzahl Meldungen exakt: TOP-THEMA 2, DEUTSCHLAND 3, EUROPA 3, WELT 3, SPORT 2, KURIOSES 1, WETTER 1. "
        "4) Jede Meldung mindestens drei Saetze. "
        "5) Jede Meldung maximal 700 Zeichen. "
        "6) Kein Podcast-, Newsletter-, Feedback- oder Quellenstil. "
        "7) Gesamter Text maximal 9000 Zeichen. "
        "Gib nur den finalen Text zurueck, ohne Codeblock.\n\n"
        f"{body}"
    )
    return _openai_chat_completion(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "developer", "content": "Du bist Chef vom Nachrichtenradio-Lektorat."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    ).strip()


def _repair_body_with_openai(api_key: str, model: str, body: str) -> str:
    prompt = (
        "Korrigiere den Text strikt in dieses Format und gib nur den Text zurueck: "
        "TOP-THEMA, DEUTSCHLAND, EUROPA, WELT, SPORT, KURIOSES, WETTER. "
        "Unter jeder Ueberschrift nur Zeilen mit '- '. "
        "Anzahl Meldungen exakt: TOP-THEMA 2, DEUTSCHLAND 3, EUROPA 3, WELT 3, SPORT 2, KURIOSES 1, WETTER 1. "
        "Jede Meldung mindestens drei kurze Aussagesaetze, maximal 700 Zeichen. "
        "Keine Werbung, keine Rueckfragen, keine E-Mails, keine Quellen. "
        "Maximal 9000 Zeichen.\n\n"
        f"{body}"
    )
    return _openai_chat_completion(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "developer", "content": "Du reparierst nur Format und Kuerze fuer Nachrichtensendungen."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    ).strip()

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
    def curious_history_path() -> str:
        custom = os.environ.get("CURIOUS_HISTORY_FILE", "").strip()
        if custom:
            return custom
        return os.path.join("output", "hourly_blocks", "curious_history.json")

    def load_history(path: str) -> List[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        entries = data.get("entries", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            return []
        out: List[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            link = str(entry.get("link", "")).strip()
            ts = str(entry.get("ts", "")).strip()
            if link and ts:
                out.append({"link": link, "ts": ts})
        return out

    def save_history(path: str, entries: List[dict]) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    candidates: List[tuple[int, FeedItem]] = []
    for pool in (primary_pool, fallback_pool):
        for item in pool:
            link = item.get("link", "")
            if not link or link in used_links:
                continue
            if not _is_recent_item(item, max_age_hours=30):
                continue
            if _is_noise_item(item):
                continue
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            score = 0
            if any(word in haystack for word in CURIOUS_POSITIVE_KEYWORDS):
                score += 8
            if "/wissen/" in link or "/multimedia/" in link or "/wetter/" in link:
                score += 5
            if "/inland/" in link or "/ausland/" in link:
                score -= 2
            if any(word in haystack for word in CURIOUS_NEGATIVE_KEYWORDS):
                score -= 10
            candidates.append((score, item))

    candidates = sorted(candidates, key=lambda pair: pair[0], reverse=True)
    if not candidates:
        return None

    now = datetime.now().astimezone()
    history = load_history(curious_history_path())
    repeat_block = timedelta(hours=int(os.environ.get("CURIOUS_REPEAT_BLOCK_HOURS", str(CURIOUS_REPEAT_BLOCK_HOURS))))
    keep_window = timedelta(days=int(os.environ.get("CURIOUS_HISTORY_KEEP_DAYS", str(CURIOUS_HISTORY_KEEP_DAYS))))

    recent_links: set[str] = set()
    kept_entries: List[dict] = []
    for entry in history:
        link = entry["link"]
        ts_raw = entry["ts"]
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=now.tzinfo)
            ts = ts.astimezone()
        except Exception:
            continue
        if now - ts <= keep_window:
            kept_entries.append({"link": link, "ts": ts.isoformat()})
        if now - ts <= repeat_block:
            recent_links.add(link)

    chosen: Optional[FeedItem] = None
    chosen_score = -10_000
    for score, item in candidates:
        link = item.get("link", "")
        if score <= 0:
            continue
        if link in recent_links:
            continue
        chosen = item
        chosen_score = score
        break

    # Fallback: falls nichts Neues verfuegbar ist, trotzdem bestes positives Item senden.
    if chosen is None:
        for score, item in candidates:
            if score > 0:
                chosen = item
                chosen_score = score
                break

    if chosen and chosen_score > 0:
        link = chosen.get("link", "")
        used_links.add(link)
        kept_entries.append({"link": link, "ts": now.isoformat()})
        save_history(curious_history_path(), kept_entries[-300:])
        return chosen
    return None


def _safe_fetch_feed(name: str) -> List[FeedItem]:
    url = TAGESSCHAU_FEEDS[name]
    try:
        return fetch_rss_items(url, max_items=60)
    except Exception:
        return []


def _serialize_sections_for_debug(section_items: Dict[str, List[FeedItem]]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for section in SECTION_ORDER:
        items = section_items.get(section, [])
        out[section] = [
            {
                "title": _clean_text(item.get("title", "")),
                "description": _clean_text(item.get("description", "")),
                "link": item.get("link", ""),
                "pubDate": item.get("pubDate", ""),
            }
            for item in items
        ]
    return out


def build_tagesschau_news_package(
    sport_items: int = 2,
    api_key: Optional[str] = None,
    openai_model: str = DEFAULT_OPENAI_MODEL,
) -> dict:
    all_items = _filter_items(_safe_fetch_feed("all"))
    inland_items = _filter_items(_safe_fetch_feed("inland"))
    europa_items = _filter_items(_safe_fetch_feed("europa"))
    ausland_items = _filter_items(_safe_fetch_feed("ausland"))
    wissen_items = _filter_items(_safe_fetch_feed("wissen"))
    wetter_items = _filter_items(_safe_fetch_feed("wetter"), max_desc_chars=260)
    sport_feed_items = _filter_items(_safe_fetch_feed("sport"), max_desc_chars=260)

    if not all_items:
        raise RuntimeError("Tagesschau-Feed konnte nicht geladen werden")

    used_links: set[str] = set()
    section_items: Dict[str, List[FeedItem]] = {name: [] for name in SECTION_ORDER}

    section_items["TOP-THEMA"] = _pick_items(all_items, SECTION_TARGET_COUNTS["TOP-THEMA"], used_links)

    deutschland = _pick_items(inland_items, SECTION_TARGET_COUNTS["DEUTSCHLAND"], used_links)
    section_items["DEUTSCHLAND"] = _fill_with_fallback(
        deutschland,
        SECTION_TARGET_COUNTS["DEUTSCHLAND"],
        used_links,
        [all_items],
        predicate=lambda it: "/inland/" in it.get("link", ""),
    )

    europa = _pick_items(europa_items, SECTION_TARGET_COUNTS["EUROPA"], used_links)
    section_items["EUROPA"] = _fill_with_fallback(
        europa,
        SECTION_TARGET_COUNTS["EUROPA"],
        used_links,
        [all_items, ausland_items],
        predicate=lambda it: "/ausland/europa/" in it.get("link", ""),
    )

    welt = _pick_items(
        ausland_items,
        SECTION_TARGET_COUNTS["WELT"],
        used_links,
        predicate=lambda it: "/ausland/europa/" not in it.get("link", ""),
    )
    section_items["WELT"] = _fill_with_fallback(
        welt,
        SECTION_TARGET_COUNTS["WELT"],
        used_links,
        [all_items],
        predicate=lambda it: "/ausland/" in it.get("link", "") and "/ausland/europa/" not in it.get("link", ""),
    )

    sport_count = SECTION_TARGET_COUNTS["SPORT"] if int(sport_items) > 0 else 0
    sport = _pick_items(sport_feed_items, sport_count, used_links)
    if not sport and sport_count > 0:
        sport = _pick_items(
            all_items,
            sport_count,
            used_links,
            predicate=lambda it: "/sport/" in it.get("link", ""),
        )
    section_items["SPORT"] = sport

    curious = _select_curious_item(used_links, all_items, wissen_items)
    section_items["KURIOSES"] = [curious] if curious else []

    wetter_de = _pick_items(
        wetter_items,
        1,
        used_links,
        predicate=lambda it: "/wetter/deutschland/" in it.get("link", ""),
    )
    if not wetter_de:
        wetter_de = _pick_items(wetter_items, 1, used_links)
    section_items["WETTER"] = wetter_de

    local_section_lines: Dict[str, List[str]] = {}
    item_by_id: Dict[str, str] = {}
    line_to_section: Dict[str, str] = {}
    idx = 1
    for section in SECTION_ORDER:
        lines: List[str] = []
        for item in section_items.get(section, []):
            if section == "WETTER":
                rendered = _render_weather_item(item, max_chars=240)
            elif section == "KURIOSES":
                rendered = _render_item(item, max_chars=300)
            else:
                rendered = _render_item(item, max_chars=340)
            if not rendered:
                continue
            item_id = f"n{idx:02d}"
            idx += 1
            item_by_id[item_id] = rendered
            line_to_section[item_id] = section
            lines.append(rendered)
        local_section_lines[section] = lines

    mode_used = "local"
    final_section_lines = {name: list(lines) for name, lines in local_section_lines.items()}
    if api_key and item_by_id:
        try:
            redacted = _redact_items_with_openai(api_key, openai_model, item_by_id)
            if redacted:
                grouped: Dict[str, List[str]] = {name: [] for name in SECTION_ORDER}
                for item_id, original in item_by_id.items():
                    section = line_to_section[item_id]
                    grouped[section].append(redacted.get(item_id, original))
                final_section_lines = grouped
                draft_body = _compose_body_from_sections(grouped)
                polished = _polish_body_with_openai(api_key, openai_model, draft_body)
                if _validate_broadcast_body(polished):
                    mode_used = "openai"
                    body = polished
                else:
                    repaired = _repair_body_with_openai(api_key, openai_model, polished)
                    if _validate_broadcast_body(repaired):
                        mode_used = "openai-repair"
                        body = repaired
                    elif _validate_broadcast_body(draft_body):
                        mode_used = "openai-draft"
                        body = draft_body
                    else:
                        body = _compose_body_from_sections(local_section_lines)
            else:
                body = _compose_body_from_sections(local_section_lines)
        except Exception:
            body = _compose_body_from_sections(local_section_lines)
    else:
        body = _compose_body_from_sections(local_section_lines)

    if not _validate_broadcast_body(body):
        body = _compose_body_from_sections(local_section_lines)
        mode_used = "local"

    lines: List[str] = []
    lines.append(_build_intro_text())
    lines.append("")
    lines.append(body)
    lines.append("")
    lines.append(_build_outro_text())
    text = "\n".join(lines).strip()

    return {
        "text": text,
        "body": body,
        "section_lines": final_section_lines,
        "raw_sections": _serialize_sections_for_debug(section_items),
        "mode_used": mode_used,
        "char_count": len(text),
    }


def build_tagesschau_news_text(
    sport_items: int = 2,
    api_key: Optional[str] = None,
    openai_model: str = DEFAULT_OPENAI_MODEL,
) -> str:
    return build_tagesschau_news_package(
        sport_items=sport_items,
        api_key=api_key,
        openai_model=openai_model,
    )["text"]


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
    redaction_mode = os.environ.get("TAGESSCHAU_REDACTION_MODE", "auto").strip().lower()

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
        api_key = os.environ.get("OPENAI_API_KEY")
        use_api_key = None
        if redaction_mode in ("auto", "openai", "required"):
            use_api_key = api_key
        if redaction_mode == "required" and not use_api_key:
            raise SystemExit("OPENAI_API_KEY missing for TAGESSCHAU_REDACTION_MODE=required")
        text = build_tagesschau_news_text(
            sport_items=args.sport_items,
            api_key=use_api_key,
            openai_model=openai_model,
        )

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
