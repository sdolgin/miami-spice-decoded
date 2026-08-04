import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review_queue import save_decision


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.review_path = Path(self.temporary.name) / "valuation-review.json"
        self.review = {"restaurants": [{
            "name": "Example",
            "tiers": [{"meal": "dinner", "price": 50, "courses": [{
                "course": "Entrees",
                "choices": [{
                    "spiceName": "Dish",
                    "matches": [{
                        "regularName": "Regular Dish",
                        "regularPrice": 22,
                        "supplement": 2,
                        "effectiveValue": 20,
                        "confidence": 0.6,
                        "sourceUrl": "https://example.test/menu",
                        "sourceText": "Regular Dish 22",
                    }],
                    "decision": None,
                }],
            }]}],
        }]}
        self.review_path.write_text(json.dumps(self.review), encoding="utf-8")
        self.key = {"restaurant": "Example", "meal": "dinner", "price": 50, "course": "Entrees", "spiceName": "Dish"}

    def tearDown(self):
        self.temporary.cleanup()

    def test_accept_candidate_is_snapshotted_and_saved(self):
        with patch("review_queue.REVIEW", self.review_path):
            decision = save_decision(self.key, {"type": "accept", "matchIndex": 0})

        saved = json.loads(self.review_path.read_text(encoding="utf-8"))
        self.assertEqual(decision["match"]["effectiveValue"], 20)
        self.assertEqual(saved["restaurants"][0]["tiers"][0]["courses"][0]["choices"][0]["decision"], decision)

    def test_manual_evidence_deducts_supplement(self):
        request = {
            "type": "manual",
            "regularName": "Manual Dish",
            "regularPrice": 25,
            "supplement": 5,
            "sourceUrl": "https://example.test/current-menu",
            "sourceText": "Manual Dish 25",
        }
        with patch("review_queue.REVIEW", self.review_path):
            decision = save_decision(self.key, request)

        self.assertEqual(decision["match"]["effectiveValue"], 20)
        self.assertTrue(decision["match"]["reviewed"])


if __name__ == "__main__":
    unittest.main()