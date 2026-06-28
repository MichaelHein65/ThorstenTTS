#!/usr/bin/env python3
"""Persistent, conservative pronunciation learning for Thorsten/Piper news."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from urllib.request import Request, urlopen
from datetime import datetime
from pathlib import Path
from typing import Any

import fcntl


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LEARNED_CATALOG_PATH = BASE_DIR / "thorsten_tts_learned.json"
DEFAULT_AUDIT_DIR = BASE_DIR / "output" / "pronunciation_learning"
ACRONYM_RE = re.compile(r"\b[A-ZÄÖÜ]{2,6}\b")
SAFE_SOURCE_RE = re.compile(r"^[0-9A-Za-zÀ-ÿÄÖÜäöüßŞşĆćČčŁłŽž'’ .\-/]{2,80}$")
SAFE_TTS_RE = re.compile(r"^[0-9A-Za-zÀ-ÿÄÖÜäöüß'’ .\-]{2,120}$")
SECTION_LABELS = {
    "DEUTSCHLAND", "EUROPA", "KURIOSES", "PANORAMA", "POLITIK", "SPORT",
    "THEMA", "TOP", "WELT", "WETTER", "WIRTSCHAFT",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _empty_catalog() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "entries": {}}


def load_learned_catalog(path: Path = DEFAULT_LEARNED_CATALOG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_catalog()
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        return _empty_catalog()
    return payload


def active_replacements(path: Path = DEFAULT_LEARNED_CATALOG_PATH) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for source, entry in load_learned_catalog(path).get("entries", {}).items():
        if not isinstance(entry, dict) or entry.get("status") != "active":
            continue
        target = entry.get("tts")
        if isinstance(source, str) and isinstance(target, str) and source and target:
            replacements[source] = target
    return replacements


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _extract_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("pronunciation response is not a JSON object")
    return payload


def _known_sources(static_catalog: dict[str, Any], learned: dict[str, Any]) -> set[str]:
    known = set(static_catalog.get("literal_replacements", {}))
    known.update(static_catalog.get("acronym_replacements", {}))
    known.update(learned.get("entries", {}))
    return known


def _local_acronym_suggestions(text: str, known: set[str]) -> list[dict[str, Any]]:
    suggestions = []
    for term in sorted(set(ACRONYM_RE.findall(text))):
        if term in known or term in SECTION_LABELS:
            continue
        suggestions.append({
            "source": term,
            "tts": " ".join(term),
            "confidence": 1.0,
            "kind": "acronym",
            "reason": "Unbekannte Grossbuchstaben-Abkuerzung; buchstabenweise sprechen.",
            "origin": "deterministic",
        })
    return suggestions


def _split_for_analysis(text: str, max_chars: int = 2200) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for block in blocks:
        projected = current_length + len(block) + (2 if current else 0)
        if current and projected > max_chars:
            chunks.append("\n\n".join(current))
            current = [block]
            current_length = len(block)
        else:
            current.append(block)
            current_length = projected
    if current:
        chunks.append("\n\n".join(current))
    return chunks or ([text] if text.strip() else [])


def _ai_suggestions(
    text: str,
    known: set[str],
    api_key: str,
    model: str,
) -> list[dict[str, Any]]:
    known_preview = sorted(known, key=str.casefold)
    system_prompt = (
        "Du bist Aussprache-Lektor fuer deutsche Radionachrichten, gesprochen mit Piper/Thorsten. "
        "Finde nur Begriffe im gelieferten Text, die eine deutsche TTS-Stimme wahrscheinlich falsch ausspricht: "
        "fremdsprachige Personen- und Ortsnamen, Marken, Anglizismen und ungewoehnliche Abkuerzungen. "
        "Gib als tts eine leicht lesbare deutsche Lautschreibweise in normalen Buchstaben aus, niemals IPA. "
        "Veraendere keine normalen deutschen Woerter. Erfinde keine Begriffe. Bei Unsicherheit keinen Eintrag liefern."
    )
    suggestions: list[dict[str, Any]] = []
    for chunk_number, chunk in enumerate(_split_for_analysis(text), start=1):
        user_prompt = (
            "Pruefe diesen Abschnitt des Nachrichtentextes Wort fuer Wort. Bereits bekannte Begriffe nicht erneut ausgeben.\n\n"
            f"BEKANNT:\n{json.dumps(known_preview, ensure_ascii=False)}\n\n"
            f"ABSCHNITT {chunk_number}:\n{chunk}\n\n"
            "Antworte als JSON-Objekt mit entries. Jeder Eintrag: source (exakt wie im Text), tts, "
            "confidence zwischen 0 und 1, kind und eine kurze reason. Nur Eintraege ab eigener Sicherheit 0.90. "
            "Format: {\"entries\":[{\"source\":\"Vucic\",\"tts\":\"Wutschitsch\","
            "\"confidence\":0.97,\"kind\":\"person\",\"reason\":\"serbischer Name\"}]}"
        )
        request_payload = {
            "model": model,
            "messages": [
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        raw = response_payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not raw:
            raise RuntimeError(f"OpenAI pronunciation response for chunk {chunk_number} did not include content")
        entries = _extract_json(raw).get("entries", [])
        if not isinstance(entries, list):
            raise ValueError(f"pronunciation response entries for chunk {chunk_number} is not a list")
        suggestions.extend(entry for entry in entries if isinstance(entry, dict))
    return suggestions


def _validate_suggestion(
    item: dict[str, Any],
    text: str,
    minimum_confidence: float,
) -> tuple[dict[str, Any] | None, str | None]:
    source = str(item.get("source", "")).strip()
    target = str(item.get("tts", "")).strip()
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not source or source not in text:
        return None, "source_not_in_text"
    if source == target:
        return None, "unchanged"
    if confidence < minimum_confidence:
        return None, "low_confidence"
    if not SAFE_SOURCE_RE.fullmatch(source) or not SAFE_TTS_RE.fullmatch(target):
        return None, "unsafe_characters_or_length"
    if any(mark in target for mark in ("\n", "\r", "\t", "!", "?", ":", ";")):
        return None, "unsafe_punctuation"
    return {
        "source": source,
        "tts": target,
        "confidence": round(min(confidence, 1.0), 3),
        "kind": str(item.get("kind", "unknown"))[:40],
        "reason": str(item.get("reason", ""))[:240],
        "origin": str(item.get("origin", "openai"))[:40],
    }, None


def learn_pronunciations(
    text: str,
    static_catalog: dict[str, Any],
    learned_path: Path = DEFAULT_LEARNED_CATALOG_PATH,
    *,
    api_key: str = "",
    model: str = "gpt-4o-mini",
    minimum_confidence: float = 0.90,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "enabled": True,
        "model": model,
        "minimum_confidence": minimum_confidence,
        "accepted": [],
        "rejected": [],
        "conflicts": [],
        "error": None,
    }
    lock_path = learned_path.with_suffix(learned_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        learned = load_learned_catalog(learned_path)
        known = _known_sources(static_catalog, learned)
        suggestions = _local_acronym_suggestions(text, known)
        if api_key:
            try:
                suggestions.extend(_ai_suggestions(text, known, api_key, model))
            except Exception as exc:
                report["error"] = f"{type(exc).__name__}: {exc}"
        else:
            report["error"] = "OPENAI_API_KEY missing; only deterministic acronym learning ran"

        accepted_by_source: dict[str, dict[str, Any]] = {}
        for raw_item in suggestions:
            item, rejection = _validate_suggestion(raw_item, text, minimum_confidence)
            if item is None:
                report["rejected"].append({"item": raw_item, "reason": rejection})
                continue
            source = item["source"]
            prior = accepted_by_source.get(source)
            if prior and prior["tts"] != item["tts"]:
                winner = max((prior, item), key=lambda entry: entry["confidence"])
                loser = item if winner is prior else prior
                accepted_by_source[source] = winner
                report["conflicts"].append({"source": source, "kept": winner["tts"], "ignored": loser["tts"]})
            else:
                accepted_by_source[source] = item

        entries = learned.setdefault("entries", {})
        now = _now()
        changed = False
        for source, item in accepted_by_source.items():
            existing = entries.get(source)
            if isinstance(existing, dict):
                existing["last_seen"] = now
                existing["occurrences"] = int(existing.get("occurrences", 0)) + text.count(source)
                if existing.get("tts") != item["tts"]:
                    report["conflicts"].append({
                        "source": source,
                        "kept": existing.get("tts"),
                        "ignored": item["tts"],
                    })
                changed = True
                continue
            entries[source] = {
                "tts": item["tts"],
                "status": "active",
                "confidence": item["confidence"],
                "kind": item["kind"],
                "reason": item["reason"],
                "origin": item["origin"],
                "first_seen": now,
                "last_seen": now,
                "occurrences": text.count(source),
            }
            report["accepted"].append(item)
            changed = True

        if changed:
            learned["updated_at"] = now
            _atomic_write_json(learned_path, learned)
        report["active_entry_count"] = sum(
            1 for entry in entries.values() if isinstance(entry, dict) and entry.get("status") == "active"
        )
    return report


def write_learning_audit(
    original_text: str,
    tts_text: str,
    report: dict[str, Any],
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    digest = hashlib.sha256(original_text.encode("utf-8")).hexdigest()[:10]
    output_path = audit_dir / f"pronunciation_{timestamp}_{digest}.json"
    _atomic_write_json(output_path, {
        "generated_at": _now(),
        "original_text": original_text,
        "tts_text": tts_text,
        "learning": report,
    })
    return output_path
