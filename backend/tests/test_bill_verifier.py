"""Tests for multi-reader bill verification (no network, no database).

    cd backend
    ..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import bill_verifier as bv

TODAY = date(2026, 11, 25)

# Synthetic text layer shaped like a real digital tax invoice.
PDF_TEXT = """
Tax Invoice  Original for Recipient
KARNANI SOLVEX PVT LTD.  GSTIN: 08AADCK2977N1ZW
Bill To: SHREE NATH INDUSTRIES GSTIN 08ADRPK4652L2ZW
Invoice No. DOC/26-27/1044   Dated 23-Nov-26
Vehicle No. RJ-14-GG-3752
De-oiled Mustard Cake  351.60 Qtl  @ 2,830.00   9,95,028.00
IGST 5%  49,751.40
Grand Total 10,44,779.00
"""

GOOD = {
    "vendor_name": "KARNANI SOLVEX PVT LTD.", "bill_number": "1044", "bill_date": "23-Nov-26",
    "vehicle_number": "RJ14GG3752", "quantity_qtl": 351.6, "rate_per_qtl": 2830.0,
    "total_amount": 1044779, "gstin_vendor": "08AADCK2977N1ZW",
}


def reading(**over):
    d = dict(GOOD)
    d.update(over)
    return d


class NormaliserTests(unittest.TestCase):
    def test_dates(self):
        for raw in ("23-Nov-26", "23-11-2026", "23/11/26", "2026-11-23", "23 November 2026", "23.11.2026"):
            self.assertEqual(bv.norm_date(raw), "2026-11-23", raw)
        self.assertIsNone(bv.norm_date("31-02-2026"))

    def test_bill_number(self):
        self.assertEqual(bv.norm_bill_number("DOC/26-27/01044"), "1044")
        self.assertEqual(bv.norm_bill_number("Invoice No. 184"), "184")

    def test_gstin_checksum(self):
        self.assertTrue(bv.gstin_checksum_ok("08AADCK2977N1ZW"))
        self.assertFalse(bv.gstin_checksum_ok("08AADCK2977N1ZX"))

    def test_vehicle_format(self):
        self.assertTrue(bv.vehicle_format_ok(bv.norm_vehicle("RJ-14-GG-3752")))
        self.assertFalse(bv.vehicle_format_ok(bv.norm_vehicle("RJ14GG37")))


class VerifyTests(unittest.TestCase):
    def test_two_agreeing_readers_auto_ok(self):
        out = bv.verify_bill([("gemini", reading()), ("groq_text", reading())], PDF_TEXT, today=TODAY)
        self.assertTrue(out["auto_approve_ok"], out["review_reasons"])
        self.assertEqual(out["confidence"], 1.0)
        self.assertEqual(out["values"]["bill_date"], "2026-11-23")

    def test_mt_read_as_quintal_is_resolved_by_math(self):
        # Two readers took "43.53" (printed in MT) as quintals; one read 435.3 correctly.
        good = {"vendor_name": "PITAMBAR SOLVEX", "bill_number": "1675", "bill_date": "23-11-2026",
                "vehicle_number": "RJ02GB6197", "quantity_qtl": 435.3, "rate_per_qtl": 2924.18,
                "total_amount": 1336542}
        bad1 = dict(good, quantity_qtl=43.53, rate_per_qtl=None)
        bad2 = dict(good, quantity_qtl=43.53, rate_per_qtl=28800)
        out = bv.verify_bill([("gemini", good), ("mistral", bad1), ("groq", bad2)], None, today=TODAY)
        self.assertAlmostEqual(out["values"]["quantity_qtl"], 435.3, places=2)
        self.assertAlmostEqual(out["values"]["rate_per_qtl"], 2924.18, places=1)
        self.assertTrue(out["checks"]["math"])

    def test_dropped_digit_in_total_is_caught_by_text(self):
        bad = reading(total_amount=104477.9)
        out = bv.verify_bill([("gemini", reading()), ("mistral", bad)], PDF_TEXT, today=TODAY)
        self.assertEqual(out["values"]["total_amount"], 1044779)
        self.assertEqual(out["fields"]["total_amount"]["status"], "resolved_by_text")

    def test_majority_overruled_by_printed_text(self):
        # Two readers guessed the same wrong truck; the PDF text shows the real one.
        out = bv.verify_bill(
            [("a", reading(vehicle_number="RJ14GG3725")), ("b", reading(vehicle_number="RJ14GG3725")),
             ("c", reading())],
            PDF_TEXT, today=TODAY,
        )
        self.assertEqual(out["values"]["vehicle_number"], "RJ14GG3752")

    def test_disagreement_without_text_goes_to_review(self):
        out = bv.verify_bill([("gemini", reading()), ("mistral", reading(vehicle_number="RJ02B1515"))], None, today=TODAY)
        self.assertFalse(out["auto_approve_ok"])
        self.assertEqual(out["fields"]["vehicle_number"]["status"], "conflict")
        self.assertTrue(any("Truck number" in r for r in out["review_reasons"]))

    def test_single_reader_never_auto_ok_without_text(self):
        out = bv.verify_bill([("gemini", reading())], None, today=TODAY)
        self.assertFalse(out["auto_approve_ok"])
        self.assertLessEqual(out["confidence"], 0.6)

    def test_single_reader_grounded_by_text_is_ok(self):
        out = bv.verify_bill([("gemini", reading())], PDF_TEXT, today=TODAY)
        self.assertTrue(out["auto_approve_ok"], out["review_reasons"])

    def test_math_mismatch_blocks_auto(self):
        r = reading(rate_per_qtl=2380.0)
        out = bv.verify_bill([("a", r), ("b", r)], None, today=TODAY)
        self.assertFalse(out["checks"]["math"])
        self.assertFalse(out["auto_approve_ok"])

    def test_old_or_future_date_flagged(self):
        r = reading(bill_date="14-03-2026")
        out = bv.verify_bill([("a", r), ("b", r)], None, today=TODAY)
        self.assertFalse(out["checks"]["date_sane"])
        self.assertFalse(out["auto_approve_ok"])

    def test_bad_gstin_flagged(self):
        r = reading(gstin_vendor="08AADCK2977N1ZX")
        out = bv.verify_bill([("a", r), ("b", r)], None, today=TODAY)
        self.assertFalse(out["checks"]["vendor_gstin_checksum"])
        self.assertFalse(out["auto_approve_ok"])

    def test_printed_unit_converted_deterministically(self):
        r = reading(quantity_qtl=35.16, quantity_printed=35.16, quantity_unit_printed="M.T.",
                    rate_per_qtl=28300, rate_printed=28300, rate_unit_printed="MT")
        out = bv.verify_bill([("a", r), ("b", reading())], None, today=TODAY)
        self.assertAlmostEqual(out["values"]["quantity_qtl"], 351.6)
        self.assertAlmostEqual(out["values"]["rate_per_qtl"], 2830.0)
        self.assertEqual(out["fields"]["quantity_qtl"]["status"], "agreed")

    def test_failed_readers_ignored(self):
        out = bv.verify_bill([("openrouter", {"error": "429"}), ("gemini", reading()), ("groq", reading())],
                             None, today=TODAY)
        self.assertIn("openrouter", out["sources_failed"])
        self.assertTrue(out["auto_approve_ok"])


if __name__ == "__main__":
    unittest.main()
