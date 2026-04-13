#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_CATALOG_PATH = Path(__file__).with_name("thorsten_tts_catalog.json")

_UNITS = {
    0: "null",
    1: "eins",
    2: "zwei",
    3: "drei",
    4: "vier",
    5: "fuenf",
    6: "sechs",
    7: "sieben",
    8: "acht",
    9: "neun",
    10: "zehn",
    11: "elf",
    12: "zwoelf",
    13: "dreizehn",
    14: "vierzehn",
    15: "fuenfzehn",
    16: "sechzehn",
    17: "siebzehn",
    18: "achtzehn",
    19: "neunzehn",
}

_TENS = {
    20: "zwanzig",
    30: "dreissig",
    40: "vierzig",
    50: "fuenfzig",
    60: "sechzig",
    70: "siebzig",
    80: "achtzig",
    90: "neunzig",
}

_ORDINAL_EXACT = {
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
}


def _load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> dict[str, str]:
    if not path.exists():
        return {"literal_replacements": {}, "acronym_replacements": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "literal_replacements": payload.get("literal_replacements", {}),
        "acronym_replacements": payload.get("acronym_replacements", {}),
    }


def _cardinal_to_german(number: int) -> str:
    if number < 20:
        return _UNITS[number]
    if number < 100:
        tens = (number // 10) * 10
        ones = number % 10
        if ones == 0:
            return _TENS[tens]
        one_word = "ein" if ones == 1 else _UNITS[ones]
        return f"{one_word}und{_TENS[tens]}"
    raise ValueError(f"Unsupported ordinal number: {number}")


def _ordinal_to_german(number: int) -> str:
    if number in _ORDINAL_EXACT:
        return _ORDINAL_EXACT[number]
    if number < 20:
        return _cardinal_to_german(number) + "te"
    return _cardinal_to_german(number) + "ste"


def _replace_jahrestag_ordinals(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        ordinal_number = int(match.group(1))
        return f"{_ordinal_to_german(ordinal_number)} Jahrestag"

    return re.sub(r"\b(\d{1,2})\.\s+Jahrestag\b", repl, text)


def _replace_leo_xiv_ordinal(text: str) -> str:
    pattern = re.compile(r"\b(?P<prefix>Papst\s+)?Leo XIV\.(?P<trailing_space>\s+)?")

    def repl(match: re.Match[str]) -> str:
        prefix = "Pabst " if match.group("prefix") else ""
        trailing_space = match.group("trailing_space") or ""
        next_index = match.end()
        if trailing_space and next_index < len(text) and text[next_index].islower():
            return f"{prefix}Leo der vierzehnte{trailing_space}"
        return f"{prefix}Leo der vierzehnte.{trailing_space}"

    text = pattern.sub(repl, text)
    text = re.sub(r"\bPapst\s+Leo XIV\b", "Pabst Leo der vierzehnte", text)
    return re.sub(r"\bLeo XIV\b", "Leo der vierzehnte", text)


def normalize_news_tts_text(text: str, catalog_path: Path | None = None) -> str:
    normalized = text
    normalized = _replace_jahrestag_ordinals(normalized)
    normalized = _replace_leo_xiv_ordinal(normalized)

    catalog = _load_catalog(catalog_path or DEFAULT_CATALOG_PATH)

    for source, target in sorted(catalog["literal_replacements"].items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(source, target)

    for source, target in sorted(catalog["acronym_replacements"].items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)

    return normalized
