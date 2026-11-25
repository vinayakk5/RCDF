"""Phase 1 regression tests: payables, payments, numbering, rejection notices, email checkpoint.

Runs on an in-memory SQLite database, so it never touches the real MySQL data.

    cd backend
    ..\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v

All quantities are quintals (legacy column names end in _mt).
"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from database import Base
import models as m
import main
from services import email_sync_service as ess


class DbCase(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        db = self.db
        self.company = m.Company(name="Shree Nath Industries")
        self.plant = m.Plant(name="Ajmer", code="AJM")
        self.material = m.Material(name="Maize", code="MAIZE")
        self.broker = m.Broker(name="Test Broker")
        db.add_all([self.company, self.plant, self.material, self.broker])
        db.flush()
        self.main_tender = m.MainTender(company_id=self.company.id, tender_code="RM-836")
        self.cycle = m.SproxxCycle(company_id=self.company.id, name="Nov-26",
                                   cycle_start=date(2026, 11, 1), cycle_end=date(2026, 11, 25),
                                   week1_end=date(2026, 11, 8), week2_end=date(2026, 11, 15))
        db.add_all([self.main_tender, self.cycle])
        db.flush()
        self.tender = m.Tender(
            company_id=self.company.id, main_tender_id=self.main_tender.id,
            cycle_id=self.cycle.id, tender_number="RM-836 Maize Ajmer", plant_id=self.plant.id,
            material_id=self.material.id, tender_mt=4400, week1_target_mt=2200,
            week1_deadline=date(2026, 11, 8), week2_deadline=date(2026, 11, 15),
        )
        db.add(self.tender)
        db.flush()
        self.deal = m.Deal(
            company_id=self.company.id, main_tender_id=self.main_tender.id, tender_id=self.tender.id,
            broker_id=self.broker.id, deal_number="D-2611-001", material_id=self.material.id,
            deal_mt=2000, rate_per_mt=2500,
        )
        db.add(self.deal)
        db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_bill(self, qty=300.0, rate=2550.0, truck="RJ01AB1234"):
        db = self.db
        b = m.Bill(
            company_id=self.company.id, main_tender_id=self.main_tender.id, tender_id=self.tender.id,
            deal_id=self.deal.id, broker_id=self.broker.id, vehicle_number=truck,
            material_id=self.material.id, material_name="Maize", qty_mt=qty, rate_per_mt=rate,
            total_amount=qty * rate, bill_date=date(2026, 11, 10), bill_number="INV-1",
            plant_id=self.plant.id, plant_name="Ajmer",
        )
        db.add(b)
        db.flush()
        return b

    def approve(self, bill):
        return main.approve_bill(bill.id, db=self.db)

    def add_receipt(self, truck, accepted, rejected, when=date(2026, 11, 12)):
        data = main.ReceiptCreate(
            vehicle_number=truck, plant_id=self.plant.id, receipt_date=when,
            accepted_mt=accepted, rejected_mt=rejected, material_id=self.material.id,
            material_name="Maize",
        )
        return main.add_receipt(data, company_id=None, main_tender_id=None, tender_id=None, db=self.db)

    def pb_for(self, bill):
        return self.db.execute(sa.select(m.PurchaseBill).where(m.PurchaseBill.bill_id == bill.id)).scalar_one()


class PayableTests(DbCase):
    def test_purchase_bill_waits_for_unloading(self):
        b = self.make_bill()
        self.approve(b)
        pb = self.pb_for(b)
        self.assertEqual(pb.status, m.PurchaseBillStatus.draft)
        self.assertEqual(float(pb.total_amount), 0)
        self.assertEqual(float(pb.billed_qty_qtl), 300)
        state = main._purchase_bill_payment_state(pb)
        self.assertEqual(state["payment_state"], "awaiting_unloading")

    def test_payable_is_accepted_qty_times_deal_rate(self):
        b = self.make_bill(qty=300, rate=2550)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=280, rejected=20)
        pb = self.pb_for(b)
        self.assertEqual(float(pb.qty_mt), 280)
        self.assertEqual(float(pb.rate_per_mt), 2500)  # deal rate, not the bill's 2550
        self.assertEqual(float(pb.total_amount), 700000)
        self.assertEqual(pb.status, m.PurchaseBillStatus.confirmed)

    def test_full_rejection_means_nothing_due(self):
        b = self.make_bill(qty=300)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=0, rejected=300)
        pb = self.pb_for(b)
        self.assertEqual(float(pb.total_amount), 0)
        self.assertEqual(main._purchase_bill_payment_state(pb)["payment_state"], "nothing_due")

    def test_payment_blocked_before_unloading(self):
        b = self.make_bill()
        self.approve(b)
        pb = self.pb_for(b)
        with self.assertRaises(HTTPException) as ctx:
            main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=1000), db=self.db)
        self.assertIn("No plant unloading result", ctx.exception.detail)

    def test_partial_payments_and_overpayment_guard(self):
        b = self.make_bill(qty=100)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=100, rejected=0)
        pb = self.pb_for(b)  # payable 250000
        r1 = main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=100000), db=self.db)
        self.assertEqual(r1["payment_state"], "partly_paid")
        self.assertEqual(r1["outstanding"], 150000)
        with self.assertRaises(HTTPException):
            main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=200000), db=self.db)
        r2 = main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=150000), db=self.db)
        self.assertEqual(r2["payment_state"], "paid")
        self.assertNotEqual(r1["voucher_number"], r2["voucher_number"])
        self.assertEqual(self.pb_for(b).status, m.PurchaseBillStatus.paid)

    def test_deleting_payment_restores_balance(self):
        b = self.make_bill(qty=100)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=100, rejected=0)
        pb = self.pb_for(b)
        r = main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=250000), db=self.db)
        main.delete_payment(r["id"], db=self.db)
        pb = self.pb_for(b)
        self.assertEqual(float(pb.paid_amount), 0)
        self.assertEqual(main._purchase_bill_payment_state(pb)["payment_state"], "unpaid")


class NumberingTests(DbCase):
    def test_numbers_never_repeat_after_delete(self):
        prefix = "PB-2611-"
        for n in ("PB-2611-001", "PB-2611-002", "PB-2611-003"):
            b = self.make_bill(truck=f"RJ01AB{n[-3:]}9"[:10])
            self.db.add(m.PurchaseBill(bill_id=b.id, deal_id=self.deal.id, broker_id=self.broker.id,
                                       pb_number=n, qty_mt=0, rate_per_mt=0, total_amount=0,
                                       bill_date=date.today()))
        self.db.flush()
        # Delete the middle one: a row-count scheme would now hand out 003 again.
        self.db.delete(self.db.execute(sa.select(m.PurchaseBill).where(m.PurchaseBill.pb_number == "PB-2611-002")).scalar_one())
        self.db.flush()
        self.assertEqual(main._next_doc_number(self.db, m.PurchaseBill.pb_number, prefix), "PB-2611-004")


class RejectionNoticeTests(DbCase):
    def pending(self, payload):
        return m.PendingIngest(
            id=1, source=m.IngestSource.email, file_name="x.pdf", file_path="x.pdf",
            document_type=m.DocumentType.rejection_notice, extracted_payload=payload,
            company_id=self.company.id,
        )

    def test_no_quantity_goes_to_review_instead_of_1000(self):
        out = main._apply_pending_action(self.db, self.pending({
            "vehicle_number": "RJ01AB1234", "plant_name": "Ajmer", "material_type": "Maize",
            "rejection_type": "partial", "reason": "Moisture high",
        }))
        self.assertTrue(out.get("manual_required"))
        self.assertEqual(self.db.execute(sa.select(sa.func.count(m.PlantReceipt.id))).scalar(), 0)

    def test_partial_rejection_updates_existing_unloading_receipt(self):
        b = self.make_bill(qty=300)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=280, rejected=0)
        out = main._apply_pending_action(self.db, self.pending({
            "vehicle_number": "RJ 01 AB 1234", "plant_name": "Ajmer", "material_type": "Maize",
            "rejection_type": "partial", "rejected_qty_qtl": 20, "reason": "Fungus",
            "rejection_date": "2026-11-13",
        }))
        self.assertIn("updated_receipt_id", out["trucks"][0])
        receipts = self.db.execute(sa.select(m.PlantReceipt)).scalars().all()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(float(receipts[0].accepted_mt), 280)
        self.assertEqual(float(receipts[0].rejected_mt), 20)
        self.assertIn("Fungus", receipts[0].rejection_reason)

    def test_complete_rejection_uses_truck_qty_and_matches_dispatch(self):
        b = self.make_bill(qty=300)
        self.approve(b)
        out = main._apply_pending_action(self.db, self.pending({
            "vehicle_number": "RJ01AB1234", "plant_name": "Ajmer", "material_type": "Maize",
            "rejection_type": "complete", "quantity_qtl": 300, "reason": "Quality",
            "rejection_date": "2026-11-12",
        }))
        self.assertIn("created_receipt_id", out["trucks"][0])
        r = self.db.get(m.PlantReceipt, out["trucks"][0]["created_receipt_id"])
        self.assertEqual(float(r.rejected_mt), 300)
        self.assertEqual(float(r.accepted_mt), 0)
        self.assertIsNotNone(r.dispatch_id)
        self.assertEqual(main._purchase_bill_payment_state(self.pb_for(b))["payment_state"], "nothing_due")


class RealLetterTests(RejectionNoticeTests):
    """Shapes taken from real plant letters: no weight printed, several trucks, Hindi."""

    def test_partly_rejected_without_qty_uses_bill_minus_unloaded(self):
        # "Partly rejected material redirected to party without unloading."
        b = self.make_bill(qty=300)
        self.approve(b)
        self.add_receipt(b.vehicle_number, accepted=262.5, rejected=0)
        out = main._apply_pending_action(self.db, self.pending({
            "plant_name": "Ajmer",
            "trucks": [{"truck_number": "RJ01AB1234", "material_type": "Maize", "rejection_type": "partial",
                        "reason": "S.F discolouration 4.76% & live insects", "rejection_date": "2026-11-12"}],
        }))
        row = out["trucks"][0]
        self.assertFalse(out["manual_required"], out)
        self.assertAlmostEqual(row["rejected_qtl"], 37.5)
        pb = self.pb_for(b)
        self.assertAlmostEqual(float(pb.qty_mt), 262.5)   # pay only what was unloaded

    def test_complete_rejection_without_qty_uses_dispatch(self):
        b = self.make_bill(qty=300)
        self.approve(b)
        out = main._apply_pending_action(self.db, self.pending({
            "plant_name": "Ajmer", "rejection_date": "2026-11-11",
            "trucks": [{"truck_number": "RJ01AB1234", "material_type": "Maize", "reason": "High moisture 11.69%"}],
        }))
        row = out["trucks"][0]
        self.assertEqual(row["rejection_type"], "complete")
        self.assertEqual(row["rejected_qtl"], 300)
        self.assertEqual(main._purchase_bill_payment_state(self.pb_for(b))["payment_state"], "nothing_due")

    def test_letter_with_two_trucks(self):
        b1 = self.make_bill(qty=266.1, truck="RJ07GD4626")
        b2 = self.make_bill(qty=243.2, truck="RJ07GE0056")
        self.approve(b1); self.approve(b2)
        out = main._apply_pending_action(self.db, self.pending({
            "plant_name": "Ajmer", "rejection_date": "2026-11-12",
            "trucks": [
                {"truck_number": "RJ07 GD 4626", "material_type": "Maize", "qty_as_per_bilty_qtl": 266.10, "reason": "High silica"},
                {"truck_number": "RJ07 GE 0056", "material_type": "Maize", "qty_as_per_bilty_qtl": 243.20, "reason": "High fibre"},
            ],
        }))
        self.assertFalse(out["manual_required"], out)
        self.assertEqual([t["rejected_qtl"] for t in out["trucks"]], [266.1, 243.2])

    def test_unknown_truck_partial_goes_to_review(self):
        out = main._apply_pending_action(self.db, self.pending({
            "plant_name": "Ajmer",
            "trucks": [{"truck_number": "RJ99ZZ9999", "rejection_type": "partial", "reason": "x"}],
        }))
        self.assertTrue(out["manual_required"])


class EmailCheckpointTests(unittest.TestCase):
    def run_cp(self, errors, prev_error=None, max_uid=200):
        with mock.patch.object(ess, "get_email_sync_checkpoint", return_value={"last_error": prev_error}):
            return ess._checkpoint_after_errors(None, mailbox="INBOX", email_user="a@b", max_uid_seen=max_uid, errors=errors)

    def test_clean_run_advances(self):
        self.assertEqual(self.run_cp([]), (200, None))

    def test_failed_message_holds_checkpoint(self):
        uid, note = self.run_cp([{"uid": "150", "error": "x"}, {"uid": "170", "error": "y"}])
        self.assertEqual(uid, 149)
        self.assertIn("retry_uid=150 attempts=1", note)

    def test_mark_seen_failure_does_not_block(self):
        self.assertEqual(self.run_cp([{"uid": "150", "error": "failed to mark seen"}])[0], 200)

    def test_gives_up_after_max_attempts(self):
        prev = f"retry_uid=150 attempts={ess.EMAIL_MAX_RETRY_ATTEMPTS}; 1 item errors this run"
        uid, note = self.run_cp([{"uid": "150", "error": "x"}], prev_error=prev)
        self.assertEqual(uid, 200)
        self.assertIn("gave_up_uid=150", note)


if __name__ == "__main__":
    unittest.main()
