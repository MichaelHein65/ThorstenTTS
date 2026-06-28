#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from news_pronunciation_learner import DEFAULT_LEARNED_CATALOG_PATH, active_replacements


DEFAULT_CATALOG_PATH = Path(__file__).with_name("thorsten_tts_catalog.json")

WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÿÄÖÜäöüß]+(?:[-'’][0-9A-Za-zÀ-ÿÄÖÜäöüß]+)*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
ACRONYM_RE = re.compile(r"\b[A-ZÄÖÜ]{2,5}\b")
MULTIWORD_RE = re.compile(
    r"\b([A-ZÄÖÜ][0-9A-Za-zÀ-ÿÄÖÜäöüß]+(?:[-'’][0-9A-Za-zÀ-ÿÄÖÜäöüß]+)*"
    r"(?:\s+[A-ZÄÖÜ][0-9A-Za-zÀ-ÿÄÖÜäöüß]+(?:[-'’][0-9A-Za-zÀ-ÿÄÖÜäöüß]+)*){1,2})\b"
)

COMMON_CAPITALIZED_WORDS = {
    "Am",
    "An",
    "Auch",
    "Bei",
    "Bis",
    "Das",
    "Dem",
    "Den",
    "Der",
    "Des",
    "Die",
    "Doch",
    "Dort",
    "Ein",
    "Eine",
    "Einem",
    "Einen",
    "Einer",
    "Es",
    "Für",
    "Im",
    "In",
    "Mit",
    "Nach",
    "Noch",
    "Nun",
    "Und",
    "Von",
    "Vom",
    "Vor",
    "Während",
    "Wenn",
    "Wie",
    "Zum",
    "Zur",
}

SECTION_LABELS = {
    "DEUTSCHLAND",
    "EUROPA",
    "PANORAMA",
    "POLITIK",
    "SPORT",
    "THEMA",
    "TOP",
    "TOP-THEMA",
    "WELT",
    "WIRTSCHAFT",
}

ANGLICISM_HINTS = {
    "comeback",
    "crew",
    "deadline",
    "feedback",
    "host",
    "interview",
    "live",
    "liveblog",
    "liveticker",
    "livestream",
    "match",
    "playoff",
    "podcast",
    "reel",
    "remis",
    "show",
    "stream",
    "streaming",
    "team",
    "update",
}

FOREIGN_MARKERS = {
    "á",
    "à",
    "â",
    "ç",
    "é",
    "è",
    "ê",
    "í",
    "ì",
    "î",
    "ñ",
    "ó",
    "ò",
    "ô",
    "ú",
    "ù",
    "û",
    "ý",
    "ÿ",
    "Á",
    "À",
    "Â",
    "Ç",
    "É",
    "È",
    "Ê",
    "Í",
    "Ì",
    "Î",
    "Ñ",
    "Ó",
    "Ò",
    "Ô",
    "Ú",
    "Ù",
    "Û",
    "Ý",
    "Ÿ",
    "ş",
    "Ş",
    "ć",
    "Ć",
    "č",
    "Č",
    "ł",
    "Ł",
    "ž",
    "Ž",
}


@dataclass
class Candidate:
    term: str
    kind: str
    score: int = 0
    occurrences: int = 0
    reasons: set[str] = field(default_factory=set)
    contexts: list[str] = field(default_factory=list)

    def add(self, reason: str, score_delta: int, context: str | None = None) -> None:
        self.score += score_delta
        self.reasons.add(reason)
        if context:
            clean_context = " ".join(context.split())
            if clean_context and clean_context not in self.contexts:
                self.contexts.append(clean_context)


def load_catalog(
    path: Path,
    learned_path: Path = DEFAULT_LEARNED_CATALOG_PATH,
) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {"literal_replacements": {}, "acronym_replacements": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    catalog = {
        "literal_replacements": payload.get("literal_replacements", {}),
        "acronym_replacements": payload.get("acronym_replacements", {}),
    }
    catalog["literal_replacements"].update(active_replacements(learned_path))
    return catalog


def load_source_text(path: Path) -> tuple[str, dict]:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = (
            payload.get("news_text_raw")
            or payload.get("news_text")
            or payload.get("text")
            or ""
        ).strip()
        return text, payload
    return path.read_text(encoding="utf-8").strip(), {}


def sentence_contexts(text: str) -> list[str]:
    return [sentence.strip() for sentence in SENTENCE_RE.split(text) if sentence.strip()]


def find_context(term: str, contexts: Iterable[str]) -> str | None:
    pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
    for sentence in contexts:
        if pattern.search(sentence):
            return sentence
    return None


def looks_foreign(term: str) -> bool:
    return any(char in FOREIGN_MARKERS for char in term)


def contains_known_source(
    term: str,
    existing_literals: set[str],
    existing_acronyms: set[str],
) -> bool:
    if term in existing_literals or term in existing_acronyms:
        return True

    tokens = set(WORD_RE.findall(term))
    split_tokens = {
        piece
        for piece in re.split(r"[\s\-–—/]+", term)
        if piece
    }
    pieces = tokens.union(split_tokens)
    if pieces.intersection(existing_literals) or pieces.intersection(existing_acronyms):
        return True

    for source in existing_literals:
        if source.endswith("-") and term.startswith(source):
            return True
        if len(source) >= 4 and source in term:
            return True
    return False


def build_lookup_urls(term: str) -> dict[str, str]:
    quoted = urllib.parse.quote(term, safe="")
    dad_query = urllib.parse.quote(f"@de {term}", safe="")
    return {
        "dad": f"https://dad.sprechwiss.uni-halle.de/dokuwiki/doku.php?id=wiki:suche&do=search&q={dad_query}",
        "duden": f"https://www.duden.de/suchen/dudenonline/{quoted}",
        "forvo": f"https://forvo.com/search/{quoted}/de/",
    }


def extract_candidates(text: str, catalog: dict[str, dict[str, str]]) -> list[Candidate]:
    existing_literals = set(catalog["literal_replacements"])
    existing_acronyms = set(catalog["acronym_replacements"])
    sentences = sentence_contexts(text)
    token_counts = Counter(WORD_RE.findall(text))
    candidates: dict[str, Candidate] = {}

    def ensure(term: str, kind: str) -> Candidate:
        candidate = candidates.get(term)
        if candidate is None:
            candidate = Candidate(term=term, kind=kind, occurrences=token_counts.get(term, text.count(term)))
            candidates[term] = candidate
        return candidate

    for acronym in sorted(set(ACRONYM_RE.findall(text))):
        if acronym in existing_acronyms or acronym in existing_literals or acronym in SECTION_LABELS:
            continue
        context = find_context(acronym, sentences)
        candidate = ensure(acronym, "abbreviation")
        candidate.add("unbekannte Abkuerzung", 6, context)

    for phrase in sorted(set(MULTIWORD_RE.findall(text))):
        parts = phrase.split()
        if parts[0] in COMMON_CAPITALIZED_WORDS or contains_known_source(phrase, existing_literals, existing_acronyms):
            continue
        if not any(looks_foreign(part) or "-" in part or any(ch.isdigit() for ch in part) for part in parts):
            continue
        context = find_context(phrase, sentences)
        candidate = ensure(phrase, "name")
        candidate.add("mehrteiliger Eigenname", 5, context)

    for token, count in token_counts.items():
        if token in existing_literals or token in existing_acronyms:
            continue
        if len(token) < 3:
            continue
        if token in SECTION_LABELS:
            continue
        if contains_known_source(token, existing_literals, existing_acronyms):
            continue

        token_lower = token.casefold()
        context = find_context(token, sentences)
        candidate: Candidate | None = None

        if looks_foreign(token):
            candidate = ensure(token, "name")
            candidate.add("fremdsprachige Zeichen", 7, context)

        if "-" in token and any(part and part[0].isupper() for part in token.split("-")):
            candidate = ensure(token, "compound")
            candidate.add("Bindestrich mit Eigenname", 4, context)

        if token_lower in ANGLICISM_HINTS:
            candidate = ensure(token, "anglicism")
            candidate.add("Anglizismus", 5, context)

        if count > 1 and candidate is not None:
            candidate.add("mehrfach im Text", min(3, count - 1), context)

    return sorted(
        candidates.values(),
        key=lambda item: (-item.score, -item.occurrences, item.term.casefold()),
    )


def render_markdown(
    source_path: Path,
    candidates: list[Candidate],
    payload: dict,
) -> str:
    lines = [
        "# Aussprache-Review",
        "",
        f"- Quelle: `{source_path}`",
        f"- Erzeugt: `{datetime.now().astimezone().isoformat(timespec='seconds')}`",
        f"- Kandidaten: `{len(candidates)}`",
        "- Hinweis: DAD und Forvo sind fuer Skript-Abfragen nicht stabil nutzbar; die Links sind fuer manuelle Browser-Pruefung gedacht.",
        "",
    ]
    if payload.get("redaction_mode_used"):
        lines.append(f"- Redaktion: `{payload['redaction_mode_used']}`")
        lines.append("")

    if not candidates:
        lines.append("Keine neuen Kandidaten gefunden.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Kandidat | Typ | Grund | Vorkommen | Kontext | DAD | Duden | Forvo |",
            "|---|---|---|---:|---|---|---|---|",
        ]
    )
    for candidate in candidates:
        lookup = build_lookup_urls(candidate.term)
        reason = ", ".join(sorted(candidate.reasons))
        context = candidate.contexts[0] if candidate.contexts else ""
        context = context.replace("|", "\\|")
        lines.append(
            "| {term} | {kind} | {reason} | {occ} | {context} | [DAD]({dad}) | [Duden]({duden}) | [Forvo]({forvo}) |".format(
                term=candidate.term.replace("|", "\\|"),
                kind=candidate.kind,
                reason=reason.replace("|", "\\|"),
                occ=candidate.occurrences,
                context=context,
                dad=lookup["dad"],
                duden=lookup["duden"],
                forvo=lookup["forvo"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def build_payload(
    source_path: Path,
    candidates: list[Candidate],
    payload: dict,
) -> dict:
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_path": str(source_path),
        "redaction_mode_used": payload.get("redaction_mode_used"),
        "candidate_count": len(candidates),
        "notes": [
            "DAD und Forvo sind fuer direkte Skript-Abfragen oft geblockt; die Links sind fuer die manuelle Browser-Pruefung gedacht.",
            "Neue hochkonfidente Aussprachen werden vor der Synthese im lernenden Thorsten-Fundus gespeichert.",
        ],
        "candidates": [
            {
                "term": candidate.term,
                "kind": candidate.kind,
                "score": candidate.score,
                "occurrences": candidate.occurrences,
                "reasons": sorted(candidate.reasons),
                "contexts": candidate.contexts[:3],
                "lookup_urls": build_lookup_urls(candidate.term),
            }
            for candidate in candidates
        ],
    }


def derive_output_path(source_path: Path, suffix: str) -> Path:
    if source_path.name.endswith(".raw.json"):
        return source_path.with_name(source_path.name[: -len(".raw.json")] + suffix)
    if source_path.suffix:
        return source_path.with_name(source_path.stem + suffix)
    return source_path.with_name(source_path.name + suffix)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Thorsten pronunciation review from a news raw.json or text file.")
    parser.add_argument("source_path", type=Path, help="Path to a raw.json or plain-text news file")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH, help="Path to thorsten_tts_catalog.json")
    parser.add_argument(
        "--learned-catalog",
        type=Path,
        default=DEFAULT_LEARNED_CATALOG_PATH,
        help="Path to the automatically learned pronunciation catalog",
    )
    parser.add_argument("--output-json", type=Path, help="Write machine-readable review JSON here")
    parser.add_argument("--output-md", type=Path, help="Write Markdown review here")
    args = parser.parse_args()

    text, payload = load_source_text(args.source_path)
    catalog = load_catalog(args.catalog, args.learned_catalog)
    candidates = extract_candidates(text, catalog)

    output_json = args.output_json or derive_output_path(args.source_path, ".pronunciation-review.json")
    output_md = args.output_md or derive_output_path(args.source_path, ".pronunciation-review.md")

    json_payload = build_payload(args.source_path, candidates, payload)
    output_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(args.source_path, candidates, payload), encoding="utf-8")

    print(output_json)
    print(output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
