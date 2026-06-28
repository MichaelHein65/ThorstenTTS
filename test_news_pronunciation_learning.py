from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_pronunciation_review import extract_candidates, load_catalog
from news_pronunciation_learner import _split_for_analysis, active_replacements, learn_pronunciations
from news_tts_normalizer import normalize_news_tts_text


class PronunciationLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.learned_path = self.root / "learned.json"
        self.catalog_path = self.root / "catalog.json"
        self.catalog_path.write_text(
            json.dumps({"literal_replacements": {}, "acronym_replacements": {}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_unknown_acronym_is_learned_without_api(self) -> None:
        report = learn_pronunciations(
            "Die WM beginnt heute.",
            {"literal_replacements": {}, "acronym_replacements": {}},
            self.learned_path,
        )
        self.assertEqual(active_replacements(self.learned_path)["WM"], "W M")
        self.assertEqual(report["accepted"][0]["origin"], "deterministic")

    def test_long_news_text_is_split_on_section_boundaries(self) -> None:
        chunks = _split_for_analysis("A\n" + ("eins " * 500) + "\n\nB\n" + ("zwei " * 500))
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("A\n"))
        self.assertTrue(chunks[1].startswith("B\n"))

    def test_review_ignores_terms_from_learned_catalog(self) -> None:
        self.learned_path.write_text(json.dumps({
            "version": 1,
            "entries": {"WM": {"tts": "W M", "status": "active"}},
        }), encoding="utf-8")
        catalog = load_catalog(self.catalog_path, self.learned_path)
        self.assertNotIn("WM", [item.term for item in extract_candidates("Die WM beginnt.", catalog)])

    @patch("news_pronunciation_learner._ai_suggestions")
    def test_only_safe_high_confidence_ai_suggestions_are_accepted(self, ai_suggestions) -> None:
        ai_suggestions.return_value = [
            {"source": "Vucic", "tts": "Wutschitsch", "confidence": 0.97, "kind": "person"},
            {"source": "Berlin", "tts": "Bärlin", "confidence": 0.70, "kind": "place"},
            {"source": "Erfunden", "tts": "Unsinn", "confidence": 0.99, "kind": "unknown"},
        ]
        report = learn_pronunciations(
            "Vucic reist nach Berlin.",
            {"literal_replacements": {}, "acronym_replacements": {}},
            self.learned_path,
            api_key="test-key",
        )
        self.assertEqual(active_replacements(self.learned_path), {"Vucic": "Wutschitsch"})
        self.assertEqual(len(report["rejected"]), 2)

    @patch("news_pronunciation_learner._ai_suggestions")
    def test_existing_pronunciation_is_not_silently_overwritten(self, ai_suggestions) -> None:
        self.learned_path.write_text(json.dumps({
            "version": 1,
            "entries": {
                "Vucic": {"tts": "Wutschitsch", "status": "active", "occurrences": 1},
            },
        }), encoding="utf-8")
        ai_suggestions.return_value = [
            {"source": "Vucic", "tts": "Wusitsch", "confidence": 0.99, "kind": "person"},
        ]
        report = learn_pronunciations(
            "Vucic spricht.",
            {"literal_replacements": {}, "acronym_replacements": {}},
            self.learned_path,
            api_key="test-key",
        )
        self.assertEqual(active_replacements(self.learned_path)["Vucic"], "Wutschitsch")
        self.assertEqual(report["conflicts"][0]["ignored"], "Wusitsch")

    def test_normalizer_uses_exact_learned_terms(self) -> None:
        self.learned_path.write_text(json.dumps({
            "version": 1,
            "entries": {
                "Vucic": {"tts": "Wutschitsch", "status": "active"},
            },
        }), encoding="utf-8")
        with patch.dict(os.environ, {"NEWS_TTS_AUTO_LEARN": "0"}, clear=False):
            result = normalize_news_tts_text(
                "Vucic und Vucics Partei.",
                catalog_path=self.catalog_path,
                learned_catalog_path=self.learned_path,
            )
        self.assertEqual(result, "Wutschitsch und Vucics Partei.")

    def test_reviewed_prosody_corrections(self) -> None:
        production_catalog = Path(__file__).with_name("thorsten_tts_catalog.json")
        self.learned_path.write_text(json.dumps({
            "version": 1,
            "entries": {
                "Tiny Forests": {"tts": "Teini Forrests", "status": "active"},
            },
        }), encoding="utf-8")
        source = (
            "indigenen Temperaturrekord Gesten Wohnmobil-Tour Pride-Parade "
            "Venezuela Match Tiny Forests"
        )
        with patch.dict(os.environ, {"NEWS_TTS_AUTO_LEARN": "0"}, clear=False):
            result = normalize_news_tts_text(
                source,
                catalog_path=production_catalog,
                learned_catalog_path=self.learned_path,
            )
        self.assertEqual(
            result,
            "indi-genen Temperatur-Rekord Ges-ten Wohn-Mobil Tour Preid Parade "
            "Vene-zuela Mätsch Teini Forrests",
        )


if __name__ == "__main__":
    unittest.main()
