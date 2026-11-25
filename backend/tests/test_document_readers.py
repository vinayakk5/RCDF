"""Double-check reading of unloading registers, tender notices and POs (no network)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import document_verifier as dv
from services import ocr_service as ocr


def row(truck, net, total=None, received=None, bags=None, **kw):
    r = {"truck_number": truck, "net_qty_mt": net, "total_qty_mt": total,
         "received_qty_mt": received, "no_of_bags": bags, "date": "2026-11-12"}
    r.update(kw)
    return r


class UnloadingVerifierTests(unittest.TestCase):
    def test_both_readers_agree(self):
        a = {"rows": [row("RJ14GA1234", 348.22, bags=700), row("RJ14GB5678", 307.68, bags=615)]}
        b = {"rows": [row("RJ 14 GA 1234", 348.2), row("RJ14GB5678", 307.7)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        self.assertFalse(v["needs_review"], v["review_reasons"])
        self.assertEqual([r["verify_status"] for r in v["rows"]], ["verified", "verified"])

    def test_disagreement_flags_row(self):
        a = {"rows": [row("RJ14GA1234", 348.22)]}
        b = {"rows": [row("RJ14GA1234", 384.22)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        self.assertTrue(v["needs_review"])
        self.assertEqual(v["rows"][0]["verify_status"], "qty_conflict")

    def test_running_total_settles_disagreement(self):
        a = {"rows": [row("RJ14GA1234", 300.0, total=300.0), row("RJ14GB5678", 250.5, total=550.5)]}
        b = {"rows": [row("RJ14GA1234", 300.0, total=300.0), row("RJ14GB5678", 205.5, total=550.5)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        self.assertEqual(v["rows"][1]["verify_status"], "confirmed_by_total")
        self.assertEqual(v["rows"][1]["net_qty_mt"], 250.5)

    def test_kg_weighbridge_converted(self):
        a = {"rows": [row("RJ14GA1234", 9850, gross_weight_kg=16850, tare_weight_kg=7000)]}
        b = {"rows": [row("RJ14GA1234", None, net_weight_kg=9850)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        r = v["rows"][0]
        self.assertEqual(r["net_qty_mt"], 98.5)
        self.assertEqual(r["verify_status"], "verified", r["verify_reasons"])

    def test_gross_minus_tare_mismatch_fails(self):
        a = {"rows": [row("RJ14GA1234", 98.5, gross_weight_kg=16850, tare_weight_kg=6000)]}
        b = {"rows": [row("RJ14GA1234", 98.5)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        self.assertEqual(v["rows"][0]["verify_status"], "check_failed")

    def test_single_reader_needs_review_and_missing_truck(self):
        v = dv.verify_unloading([("gemini", {"rows": [row("RJ14GA1234", 300)]})])
        self.assertEqual(v["rows"][0]["verify_status"], "single_reader")
        a = {"rows": [row("RJ14GA1234", 300), row("RJ14GB5678", 200)]}
        b = {"rows": [row("RJ14GA1234", 300)]}
        v = dv.verify_unloading([("gemini", a), ("mistral", b)])
        self.assertEqual(v["rows"][1]["verify_status"], "truck_not_confirmed")

    def test_bad_bag_weight_flagged(self):
        a = {"rows": [row("RJ14GA1234", 300, bags=100)]}   # 300 kg a bag
        v = dv.verify_unloading([("gemini", a), ("mistral", {"rows": [row("RJ14GA1234", 300)]})])
        self.assertEqual(v["rows"][0]["verify_status"], "check_failed")


class HeaderDocVerifierTests(unittest.TestCase):
    FIELDS = ocr._TENDER_NOTICE_FIELDS

    def test_tender_notice_agree(self):
        a = {"tender_rm_number": "RM-836", "plant_name": "Kaladera", "supply_period_start": "2026-11-01",
             "supply_period_end": "2026-11-30", "items": [{"material_type": "Maize", "quantity_qtl": 4400}]}
        b = dict(a, tender_rm_number="RM 836", plant_name="KALADERS")
        v = dv.verify_header_doc(a, b, self.FIELDS)
        self.assertFalse(v["needs_review"], v["review_reasons"])

    def test_tender_notice_qty_conflict(self):
        a = {"tender_rm_number": "RM-836", "items": [{"material_type": "Maize", "quantity_qtl": 4400}]}
        b = {"tender_rm_number": "RM-836", "items": [{"material_type": "Maize", "quantity_qtl": 440}]}
        v = dv.verify_header_doc(a, b, self.FIELDS)
        self.assertTrue(v["needs_review"])
        self.assertEqual(v["items"]["maize"], "conflict")

    def test_po_rate_conflict(self):
        a = {"po_number": "PO-1", "items": [{"material_type": "Maize", "quantity_qtl": 100, "approved_rate_per_qtl": 2650}]}
        b = {"po_number": "PO-1", "items": [{"material_type": "Maize", "quantity_qtl": 100, "approved_rate_per_qtl": 2560}]}
        v = dv.verify_header_doc(a, b, ocr._PO_FIELDS, rate_key="approved_rate_per_qtl")
        self.assertTrue(v["needs_review"])


class VerifiedUnloadingExtractorTests(unittest.TestCase):
    def test_second_reader_from_other_provider(self):
        calls = []

        async def fake(path, preferred_provider=None):
            calls.append(preferred_provider)
            if preferred_provider is None:
                return {"source": "mistral", "rows": [row("RJ14GA1234", 300.0)]}
            return {"source": preferred_provider, "rows": [row("RJ14GA1234", 300.2)]}

        with mock.patch.object(ocr, "extract_plant_unloading_sheet", side_effect=fake):
            out = asyncio.run(ocr.extract_plant_unloading_sheet_verified("/tmp/x.jpg"))
        self.assertEqual(calls, [None, "gemini"])
        self.assertFalse(out["needs_review"])
        self.assertEqual(out["rows"][0]["verify_status"], "verified")

    def test_tender_notice_runs_two_readers(self):
        async def chain(path, prompt, doc_type, preferred_provider=None):
            base = {"tender_rm_number": "RM-836", "plant_name": "Ajmer",
                    "items": [{"material_type": "Maize", "quantity_qtl": 4400}]}
            return dict(base, source=f"{preferred_provider or 'groq'}_prompt")

        with mock.patch.object(ocr, "_extract_with_prompt_chain", side_effect=chain):
            out = asyncio.run(ocr.extract_tender_notice("/tmp/x.pdf"))
        self.assertEqual(out["verification"]["readers"], ["groq_prompt", "gemini_prompt"])
        self.assertTrue(out["high_confidence"])


if __name__ == "__main__":
    unittest.main()
