"""Which of our three firms a supplier bill belongs to (from the bill's buyer)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main

IDS = {"Shree Nath Industries": 1, "Shree Vinayak Trading Company": 2, "Shree Ganpati Enterprises": 3}


def annotate(payload):
    with mock.patch.object(main, "_find_company_exact", lambda db, n: IDS.get(n)):
        return main._annotate_purchase_bill_firm(None, payload), payload


class FirmDetectionTests(unittest.TestCase):
    def test_buyer_names_our_firm(self):
        cid, p = annotate({"vendor_name": "KARNANI SOLVEX PVT LTD.", "buyer_name": "SHREE NATH INDUSTRIES"})
        self.assertEqual(cid, 1)
        self.assertEqual(p["review_reasons"], [])

    def test_buyer_spelling_variant(self):
        cid, _ = annotate({"vendor_name": "PITAMBAR SOLVEX", "buyer_name": "M/s Shree Vinayak Trading Co."})
        self.assertEqual(cid, 2)

    def test_own_firm_as_seller_is_sales_bill(self):
        cid, p = annotate({"vendor_name": "M/s Shree Nath Industeries", "buyer_name": "RCDF Ajmer"})
        self.assertIsNone(cid)
        self.assertTrue(p["looks_like_own_sales_bill"])
        self.assertFalse(p["high_confidence"])

    def test_similar_supplier_name_not_mistaken_for_our_firm(self):
        cid, p = annotate({"vendor_name": "SHREE NATH TRADERS", "buyer_name": "Shree Ganpati Enterprises"})
        self.assertEqual(cid, 3)
        self.assertNotIn("looks_like_own_sales_bill", p)

    def test_unknown_buyer_needs_review(self):
        cid, p = annotate({"vendor_name": "ABC AGRO", "buyer_name": "Some Other Feeds"})
        self.assertIsNone(cid)
        self.assertTrue(p["needs_review"])


if __name__ == "__main__":
    unittest.main()
