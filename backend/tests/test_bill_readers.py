"""Reader-chain behaviour without network calls (providers are mocked)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import ocr_service as o

GOOD = {"bill_number": "1044", "bill_date": "23-11-2026", "vehicle_number": "RJ14GG3752",
        "quantity_qtl": 351.6, "rate_per_qtl": 2830.0, "total_amount": 1044779, "vendor_name": "KARNANI SOLVEX"}


def run(coro):
    return asyncio.run(coro)


class GeminiFallbackTests(unittest.TestCase):
    def test_falls_back_to_next_model_on_overload(self):
        calls = []

        async def one(fp, prompt, tag, model):
            calls.append(model)
            if model == "m1":
                return {"source": tag, "error": "503 UNAVAILABLE high demand"}
            return dict(GOOD, source=tag)

        with mock.patch.object(o, "_extract_with_gemini_prompt_one", side_effect=one):
            res = run(o._extract_with_gemini_prompt("x.jpg", "p", "gemini_prompt", models=["m1", "m2"]))
        self.assertEqual(calls, ["m1", "m2"])
        self.assertEqual(res["model"], "m2")

    def test_does_not_retry_on_non_quota_error(self):
        calls = []

        async def one(fp, prompt, tag, model):
            calls.append(model)
            return {"source": tag, "error": "input file not found"}

        with mock.patch.object(o, "_extract_with_gemini_prompt_one", side_effect=one):
            run(o._extract_with_gemini_prompt("x.jpg", "p", "gemini_prompt", models=["m1", "m2"]))
        self.assertEqual(calls, ["m1"])


class ReaderFailedTests(unittest.TestCase):
    def test_partial_reading_is_a_voter(self):
        self.assertFalse(o._reader_failed({"rate_per_qtl": 2094.91, "bill_number": None}))

    def test_error_only_is_failed(self):
        self.assertTrue(o._reader_failed({"error": "429"}))


class PipelineTests(unittest.TestCase):
    def test_third_reader_only_on_disagreement(self):
        calls = []

        def make(name, payload):
            async def fn():
                calls.append(name)
                return dict(payload)
            return fn

        def readers(fp, agree=True):
            second = GOOD if agree else dict(GOOD, vehicle_number="RJ02B1515")
            return {
                "gemini": make("gemini", GOOD),
                "gemini_lite": make("gemini_lite", GOOD),
                "mistral": make("mistral", second),
                "groq_text": make("groq_text", GOOD),
                "openrouter": make("openrouter", GOOD),
            }

        with mock.patch.object(o, "_bill_readers", side_effect=lambda fp: readers(fp, True)):
            res = run(o.extract_bill_verified("bill.jpg"))
        self.assertEqual(calls, ["gemini", "mistral"])
        self.assertTrue(res["high_confidence"])

        calls.clear()
        with mock.patch.object(o, "_bill_readers", side_effect=lambda fp: readers(fp, False)):
            res = run(o.extract_bill_verified("bill.jpg"))
        self.assertEqual(calls, ["gemini", "mistral", "gemini_lite"])
        self.assertEqual(res["vehicle_number"], "RJ14GG3752")  # 2 of 3 agree

    def test_all_readers_down_goes_to_review(self):
        async def dead():
            return {"error": "429"}

        async def legacy(fp):
            return {"bill_number": "1", "high_confidence": True}

        with mock.patch.object(o, "_bill_readers", side_effect=lambda fp: {k: dead for k in ("gemini", "gemini_lite", "mistral", "groq_text", "openrouter")}), \
                mock.patch.object(o, "_extract_bill_legacy", side_effect=legacy):
            res = run(o.extract_bill_verified("bill.jpg"))
        self.assertFalse(res["high_confidence"])
        self.assertTrue(res["needs_review"])


if __name__ == "__main__":
    unittest.main()
