"""Auto-approval: every check must pass; shadow mode records only."""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa

import models as m
import main
from tests.test_phase1_money_and_matching import DbCase


def good_payload(**over):
    p = {
        "vendor_name": "Test Broker", "buyer_name": "Shree Nath Industries",
        "destination_plant": "Ajmer", "material_type": "Maize",
        "bill_number": "INV-77", "bill_date": "2026-11-10", "vehicle_number": "RJ01AB1234",
        "quantity_qtl": 300.0, "rate_per_qtl": 2500.0, "total_amount": 750000.0,
        "verification": {"auto_approve_ok": True}, "review_reasons": [],
    }
    p.update(over)
    return p


class AutoApprovalTests(DbCase):
    def setUp(self):
        super().setUp()
        self.age = mock.patch.object(main, "AUTO_APPROVE_MAX_BILL_AGE_DAYS", 3650)
        self.age.start()
        self.n = 0

    def tearDown(self):
        self.age.stop()
        super().tearDown()

    def ingest(self, **over):
        self.n += 1
        p = m.PendingIngest(
            source=m.IngestSource.email, file_name=f"bill{self.n}.pdf", file_path=f"/nonexistent/bill{self.n}.pdf",
            file_hash=f"h{self.n}", document_type=m.DocumentType.purchase_bill,
            extracted_payload=good_payload(**over), status=m.IngestStatus.pending,
        )
        self.db.add(p)
        self.db.flush()
        return p

    def test_clean_bill_would_be_approved_in_shadow_mode_only(self):
        p = self.ingest()
        dec = main.evaluate_auto_approval(self.db, p, mode="shadow")
        self.assertTrue(dec.would_approve, dec.checks)
        self.assertEqual(dec.predicted_deal_id, self.deal.id)
        self.assertEqual(p.status, m.IngestStatus.pending)                 # nothing done
        self.assertEqual(self.db.execute(sa.select(sa.func.count(m.Bill.id))).scalar(), 0)

    def test_any_failed_check_holds_the_bill(self):
        cases = {
            "readers_agree": {"verification": {"auto_approve_ok": False}},
            "firm_known": {"buyer_name": "Some Other Firm"},
            "not_own_sales_bill": {"vendor_name": "Shree Nath Industries"},
            "plant_known": {"destination_plant": "Nowhere"},
            "rate_within_deal": {"rate_per_qtl": 2600.0},
            "qty_within_deal": {"quantity_qtl": 5000.0},
            "deal_clear": {"bill_date": "2026-12-30"},
        }
        for check, over in cases.items():
            with self.subTest(check=check):
                dec = main.evaluate_auto_approval(self.db, self.ingest(**over), mode="shadow")
                self.assertFalse(dec.would_approve)
                self.assertIn(check, dec.failed_checks)

    def test_duplicate_bill_is_held(self):
        self.make_bill()  # bill INV-1 from Test Broker
        b = self.db.execute(sa.select(m.Bill)).scalar_one()
        b.broker_name = "Test Broker"
        self.db.flush()
        dec = main.evaluate_auto_approval(self.db, self.ingest(bill_number="INV-1"), mode="shadow")
        self.assertIn("not_duplicate", dec.failed_checks)

    def test_live_mode_books_the_bill(self):
        p = self.ingest()
        dec = main.evaluate_auto_approval(self.db, p, mode="live")
        self.assertTrue(dec.acted, dec.error)
        bill = self.db.get(m.Bill, dec.acted_bill_id)
        self.assertEqual(bill.deal_id, self.deal.id)
        self.assertEqual(bill.reviewed_by, "auto-approval")
        self.assertEqual(p.status, m.IngestStatus.processed)
        pb = self.db.execute(sa.select(m.PurchaseBill).where(m.PurchaseBill.bill_id == bill.id)).scalar_one()
        self.assertEqual(pb.status, m.PurchaseBillStatus.draft)              # still waits for unloading

    def test_pass_and_report_compare_with_person(self):
        with mock.patch.dict(os.environ, {"AUTO_APPROVE_MODE": "shadow"}):
            p = self.ingest()
            res = main.run_auto_approval_pass(self.db)
            self.assertEqual(res["evaluated"], 1)
            self.assertEqual(res["would_approve"], 1)
            # the person approves and runs it unchanged
            p.status = m.IngestStatus.approved
            main.run_pending_ingest_action(p.id, operator=None, review_notes=None, db=self.db)
            rep = main.auto_approval_report(db=self.db)
        self.assertEqual(rep["approve_agreed"], 1)
        self.assertEqual(rep["approve_wrong"], 0)
        self.assertFalse(rep["ready_for_live"])     # needs 50+


if __name__ == "__main__":
    unittest.main()
