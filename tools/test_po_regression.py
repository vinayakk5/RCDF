import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import _detect_own_company  # noqa: E402
from services.ocr_service import _normalize_purchase_order_result  # noqa: E402


class TestPurchaseOrderFallbackParser(unittest.TestCase):
    def test_raw_text_fallback_keeps_only_our_company_rows(self):
        raw_text = """
        RM-827-A Dated: 12.06.2026
        Supply period from 15.06.2026 to 30.06.2026.
        CATTLE FEED PLANT, NADBAI
        DORB 1245.000 M/s. Sharma Traders 3676.000
        DOMC 1200.000 M/s. Shree Vinayak Trading Company 3557.000
        """

        normalized = _normalize_purchase_order_result({"raw_text": raw_text, "items": []})
        items = normalized.get("items") or []

        self.assertEqual(normalized.get("tender_rm_number"), "RM-827-A")
        self.assertEqual(normalized.get("plant_name"), "Nadbai")
        self.assertTrue(normalized.get("has_our_company_winner"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].get("approved_party_name"), "Shree Vinayak Trading Company")
        self.assertEqual(items[0].get("material_type"), "Domc")


class TestCompanyFuzzyMatching(unittest.TestCase):
    def test_detect_company_from_typo_name(self):
        payload = {"winner_party_name": "M/s Shri Vinyak Tradng Compny"}
        self.assertEqual(_detect_own_company(payload), "shree vinayak trading company")

    def test_detect_company_from_item_row_when_header_missing(self):
        payload = {"items": [{"approved_party_name": "M/s Shree Nath Indstries"}]}
        self.assertEqual(_detect_own_company(payload), "shree nath industries")


if __name__ == "__main__":
    unittest.main(verbosity=2)