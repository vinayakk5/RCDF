"""Firm -> RM workspace: RM list, status, per-RM summary, inbox per RM, global search.

    cd backend
    python -m unittest tests.test_workspace -v
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa
from sqlalchemy import text

import models as m
import main
from migrations import _backfill_tender_po_links
from services import workspace as ws
from tests.test_phase1_money_and_matching import DbCase


class WorkspaceCase(DbCase):
    def setUp(self):
        super().setUp()
        self.tender.supply_start = date(2026, 7, 31)
        self.tender.supply_end = date(2026, 8, 14)
        self.po = m.PurchaseOrder(
            company_id=self.company.id, main_tender_id=self.main_tender.id, tender_id=self.tender.id,
            po_number="21064-81", po_date=date(2026, 11, 13), plant_id=self.plant.id, plant_name="Ajmer",
            total_amount=99_000_000,  # whole printed PO, incl. other parties' lines
            line_items=[{"material_type": "Maize", "approved_quantity_qtl": 5000, "approved_rate_per_qtl": 3126.91}],
            status=m.PurchaseOrderStatus.approved, source_doc_path="pending_ingests\\a\\po.pdf",
        )
        self.db.add(self.po)
        self.mt2 = m.MainTender(company_id=self.company.id, tender_code="RM-844")
        self.db.add(self.mt2)
        self.db.flush()


class RmListTests(WorkspaceCase):
    def test_list_has_numbers_and_po_value_is_only_our_lines(self):
        rows = ws.list_rms(self.db, company_id=self.company.id, status="all")
        r = next(x for x in rows if x["tender_code"] == "RM-836")
        self.assertEqual(r["po_count"], 1)
        self.assertAlmostEqual(r["po_amount"], 15_634_550.0, places=0)   # 1.56 crore, not the printed total
        self.assertEqual(r["plants"], ["Ajmer"])
        self.assertEqual(r["supply_end"], "2026-08-14")
        self.assertTrue(r["supply_over"])

    def test_status_filters_and_counts(self):
        ws.set_main_tender_status(self.db, self.main_tender, "closed")
        active = [r["tender_code"] for r in ws.list_rms(self.db, company_id=self.company.id, status="active")]
        closed = [r["tender_code"] for r in ws.list_rms(self.db, company_id=self.company.id, status="closed")]
        self.assertEqual(active, ["RM-844"])
        self.assertEqual(closed, ["RM-836"])
        self.assertEqual(ws.rm_counts(self.db, self.company.id), {"active": 1, "closed": 1, "archived": 0, "all": 2})
        # closing keeps it listed for the old selector; archiving hides it
        self.assertTrue(self.main_tender.is_active)
        ws.set_main_tender_status(self.db, self.main_tender, "archived")
        self.assertFalse(self.main_tender.is_active)
        ws.set_main_tender_status(self.db, self.main_tender, "active")
        self.assertTrue(self.main_tender.is_active)
        self.assertIsNone(self.main_tender.closed_at)

    def test_bad_status_is_refused(self):
        with self.assertRaises(ValueError):
            ws.set_main_tender_status(self.db, self.main_tender, "deleted")

    def test_text_and_date_filters(self):
        self.assertEqual([r["tender_code"] for r in ws.list_rms(self.db, status="all", q="ajmer")], ["RM-836"])
        self.assertEqual([r["tender_code"] for r in ws.list_rms(self.db, status="all", q="21064")], ["RM-836"])
        rows = ws.list_rms(self.db, status="all", date_from=date(2026, 11, 1))
        self.assertNotIn("RM-836", [r["tender_code"] for r in rows])


class RmSummaryAndDocsTests(WorkspaceCase):
    def test_summary_lists_subtenders_pos_and_doc_link(self):
        s = ws.rm_summary(self.db, self.main_tender)
        self.assertEqual(len(s["subtender_rows"]), 1)
        po = s["purchase_orders"][0]
        self.assertEqual(po["doc_url"], "/uploads/pending_ingests/a/po.pdf")
        self.assertEqual(po["our_qty_qtl"], 5000)
        self.assertEqual(po["document_total"], 99_000_000)

    def test_inbox_documents_found_by_rm_read_off_the_document(self):
        def ingest(name, dtype, payload):
            p = m.PendingIngest(file_name=name, file_path=f"pending_ingests/{name}", document_type=dtype,
                                extracted_payload=payload, source=m.IngestSource.email)
            self.db.add(p)
            return p
        ingest("sheet.pdf", m.DocumentType.plant_unloading, {"rm_number": "RM 844"})
        ingest("RM842 (Time Ext.) 8021-31.pdf", m.DocumentType.purchase_order, {"supply_period_end": "15.12.2026"})
        ingest("other.pdf", m.DocumentType.purchase_bill, {"rm_number": "RM-900"})
        self.db.flush()
        docs = ws.rm_documents(self.db, self.mt2)
        self.assertEqual([d["file_name"] for d in docs], ["sheet.pdf"])
        mt842 = m.MainTender(company_id=self.company.id, tender_code="RM-842")
        self.db.add(mt842)
        self.db.flush()
        ext = ws.rm_documents(self.db, mt842)
        self.assertEqual(ext[0]["document_type"], "tender_extension")
        self.assertEqual(ext[0]["extension"]["new_end_date"], "2026-12-15")
        rows = ws.list_rms(self.db, company_id=self.company.id, status="all")
        self.assertEqual(next(r for r in rows if r["tender_code"] == "RM-844")["pending_docs"], 1)

    def test_extension_moves_end_date_forward_only(self):
        changed = ws.apply_extension(self.db, self.main_tender, date(2026, 9, 1))
        self.assertEqual(changed[0]["to"], "2026-09-01")
        self.assertEqual(self.tender.supply_end, date(2026, 9, 1))
        self.assertEqual(ws.apply_extension(self.db, self.main_tender, date(2026, 8, 20)), [])


class SearchTests(WorkspaceCase):
    def test_search_finds_rm_po_and_truck(self):
        b = self.make_bill(truck="RJ14GB4521")
        b.bill_number = "SNI-1032"
        self.db.flush()
        self.assertIn("rms", ws.search(self.db, "844"))
        self.assertIn("purchase_orders", ws.search(self.db, "21064"))
        res = ws.search(self.db, "rj14 gb")
        self.assertEqual(res["bills"][0]["id"], b.id)
        self.assertEqual(ws.search(self.db, "x"), {})

    def test_rm_codes(self):
        self.assertEqual(ws.rm_codes_in("NITRM845"), ["RM-845"])
        self.assertEqual(ws.rm_codes_in("RM844ANIT"), ["RM-844"])
        self.assertEqual(ws.rm_codes_in("RM-200 A"), ["RM-200A"])
        self.assertEqual(ws.rm_codes_in("FARM 123"), [])


class PreviewAndBackfillTests(WorkspaceCase):
    def test_preview_uses_rm_code_not_po_number(self):
        p = main._purchase_order_subtender_preview(self.db, self.po)
        self.assertEqual(p["main_code"], "RM-836")

    def test_backfill_links_tender_to_po(self):
        self.db.commit()
        with self.engine.begin() as conn:
            _backfill_tender_po_links(conn)
        self.db.expire_all()
        self.assertEqual(self.db.get(m.Tender, self.tender.id).purchase_order_id, self.po.id)


if __name__ == "__main__":
    unittest.main()
