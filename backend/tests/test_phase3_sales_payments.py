"""Phase 3: sales bills from plant-unloaded lines, payment dues, Busy exports.

    cd backend
    python -m unittest discover -s tests -v
"""
import io
import os
import sys
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa
from fastapi import HTTPException
from openpyxl import load_workbook

import models as m
import main
from services import sales_billing as sbs
from tests.test_phase1_money_and_matching import DbCase


def fake_request(username="tester"):
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(username=username)))


class SalesCase(DbCase):
    def setUp(self):
        super().setUp()
        self.tender.sale_rate_per_qtl = 2700
        self.db.flush()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_patch = mock.patch.object(main, "get_settings",
                                                return_value=SimpleNamespace(busy_export_dir=self.tmp.name))
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        self.tmp.cleanup()
        super().tearDown()

    def receipt(self, truck, accepted, rejected=0, when=date(2026, 11, 12), tender=None, plant=None, company=None):
        t = tender or self.tender
        r = m.PlantReceipt(
            company_id=(company or self.company).id, main_tender_id=t.main_tender_id, tender_id=t.id,
            vehicle_number=truck, plant_id=(plant or self.plant).id, receipt_date=when,
            accepted_mt=accepted, rejected_mt=rejected, material_id=self.material.id,
            material_name="Maize", rm_number="RM-836",
        )
        self.db.add(r)
        self.db.flush()
        return r


class SalesBillTests(SalesCase):
    def test_combine_lines_uses_accepted_qty_and_tender_rate(self):
        r1 = self.receipt("RJ01AB0001", accepted=280, rejected=20)
        r2 = self.receipt("RJ01AB0002", accepted=300)
        sb = sbs.create_sales_bill(self.db, [r1.id, r2.id], bill_date=date(2026, 11, 20))
        self.assertEqual(float(sb.qty_mt), 580)
        self.assertEqual(float(sb.total_amount), 580 * 2700)
        self.assertEqual(len(sb.lines), 2)
        self.assertTrue(sb.sb_number.startswith("SB-2611-"))

    def test_single_line_bill(self):
        r1 = self.receipt("RJ01AB0001", accepted=250)
        sb = sbs.create_sales_bill(self.db, [r1.id])
        self.assertEqual(float(sb.qty_mt), 250)

    def test_line_cannot_be_billed_twice(self):
        r1 = self.receipt("RJ01AB0001", accepted=280)
        r2 = self.receipt("RJ01AB0002", accepted=300)
        sbs.create_sales_bill(self.db, [r1.id])
        with self.assertRaises(sbs.SalesBillError) as ctx:
            sbs.create_sales_bill(self.db, [r1.id, r2.id])
        self.assertIn("already on a sales bill", str(ctx.exception))
        # Same line twice in one request
        with self.assertRaises(sbs.SalesBillError):
            sbs.create_sales_bill(self.db, [r2.id, r2.id])

    def test_db_unique_index_blocks_double_billing(self):
        r1 = self.receipt("RJ01AB0001", accepted=280)
        sb = sbs.create_sales_bill(self.db, [r1.id])
        self.db.add(m.SalesBillLine(sales_bill_id=sb.id, receipt_id=r1.id, qty_qtl=1, rate_per_qtl=1, amount=1))
        with self.assertRaises(sa.exc.IntegrityError):
            self.db.flush()

    def test_billed_lines_leave_the_billable_list(self):
        r1 = self.receipt("RJ01AB0001", accepted=280)
        r2 = self.receipt("RJ01AB0002", accepted=300)
        self.receipt("RJ01AB0003", accepted=0, rejected=300)   # fully rejected: never billable
        lines = sbs.list_billable_lines(self.db, company_id=self.company.id)
        self.assertEqual([l["receipt_id"] for l in lines], [r1.id, r2.id])
        sbs.create_sales_bill(self.db, [r1.id])
        lines = sbs.list_billable_lines(self.db, company_id=self.company.id)
        self.assertEqual([l["receipt_id"] for l in lines], [r2.id])

    def test_cancel_frees_lines(self):
        r1 = self.receipt("RJ01AB0001", accepted=280)
        sb = sbs.create_sales_bill(self.db, [r1.id])
        sbs.cancel_sales_bill(self.db, sb)
        self.assertEqual(sb.status, m.SalesBillStatus.cancelled)
        sb2 = sbs.create_sales_bill(self.db, [r1.id])
        self.assertEqual(float(sb2.qty_mt), 280)

    def test_rate_from_po_line_when_tender_has_none(self):
        self.tender.sale_rate_per_qtl = None
        po = m.PurchaseOrder(company_id=self.company.id, main_tender_id=self.main_tender.id, tender_id=self.tender.id,
                             po_number="PO-1", plant_id=self.plant.id,
                             line_items=[{"material_type": "Maize", "approved_rate_per_qtl": 2650,
                                          "approved_quantity_qtl": 4400}])
        self.db.add(po)
        self.db.flush()
        r1 = self.receipt("RJ01AB0001", accepted=100)
        sb = sbs.create_sales_bill(self.db, [r1.id])
        self.assertEqual(float(sb.lines[0].rate_per_qtl), 2650)

    def test_no_rate_blocks_bill(self):
        self.tender.sale_rate_per_qtl = None
        r1 = self.receipt("RJ01AB0001", accepted=100)
        with self.assertRaises(sbs.SalesBillError) as ctx:
            sbs.create_sales_bill(self.db, [r1.id])
        self.assertIn("no sale rate", str(ctx.exception))

    def test_one_firm_one_plant_per_bill(self):
        other_plant = m.Plant(name="Bikaner", code="BKN")
        self.db.add(other_plant)
        self.db.flush()
        r1 = self.receipt("RJ01AB0001", accepted=100)
        r2 = self.receipt("RJ01AB0002", accepted=100, plant=other_plant)
        with self.assertRaises(sbs.SalesBillError) as ctx:
            sbs.create_sales_bill(self.db, [r1.id, r2.id])
        self.assertIn("different plants", str(ctx.exception))

    def test_late_rejection_marks_line_changed(self):
        r1 = self.receipt("RJ01AB0001", accepted=300)
        sb = sbs.create_sales_bill(self.db, [r1.id])
        r1.accepted_mt = 250
        r1.rejected_mt = 50
        self.db.flush()
        out = sbs.sales_bill_to_dict(sb)
        self.assertEqual(out["lines_changed_since_billing"], [r1.id])

    def test_endpoint_and_busy_export(self):
        r1 = self.receipt("RJ01AB0001", accepted=280)
        r2 = self.receipt("RJ01AB0002", accepted=300)
        out = main.create_sales_bill_endpoint(main.SalesBillCreate(receipt_ids=[r1.id, r2.id]),
                                              fake_request(), db=self.db)
        self.assertEqual(out["created_by"], "tester")
        with self.assertRaises(HTTPException):
            main.create_sales_bill_endpoint(main.SalesBillCreate(receipt_ids=[r1.id]), fake_request(), db=self.db)
        resp = main.export_sales_bills_busy_xlsx(main.IdListPayload(ids=[out["id"]]), company_id=None, main_tender_id=None, db=self.db)
        ws = load_workbook(io.BytesIO(resp.body)).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(rows[0][2], "VCH/BILL_NO")
        self.assertEqual(len(rows), 3)                       # header + 2 trucks, same voucher no
        self.assertEqual({r[2] for r in rows[1:]}, {out["sb_number"]})
        self.assertEqual(sorted(r[7] for r in rows[1:]), [280, 300])
        sb = self.db.get(m.SalesBill, out["id"])
        self.assertTrue(sb.busy_exported)
        self.assertEqual(sb.status, m.SalesBillStatus.sent)


class PaymentDueAndExportTests(SalesCase):
    def test_due_list_and_payment_export(self):
        b = self.make_bill(qty=300, rate=2550)
        self.approve(b)
        due = main.list_payments_due(db=self.db)
        self.assertEqual(due, [])                            # waits for unloading
        self.add_receipt(b.vehicle_number, accepted=280, rejected=20)
        due = main.list_payments_due(db=self.db)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["payable"], 280 * 2500)
        pb = self.pb_for(b)
        pay = main.create_payment(main.PaymentCreate(purchase_bill_id=pb.id, amount=700000, reference_no="UTR1"), db=self.db)
        self.assertEqual(main.list_payments_due(db=self.db), [])
        resp = main.export_payments_busy_xlsx(main.IdListPayload(ids=[pay["id"]]), company_id=None, main_tender_id=None, db=self.db)
        ws = load_workbook(io.BytesIO(resp.body)).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(rows[0][3], "ACCOUNT_DR")
        self.assertEqual(rows[1][3], "Test Broker")
        self.assertEqual(rows[1][5], 700000)
        self.assertEqual(rows[1][8], "INV-1")


if __name__ == "__main__":
    unittest.main()
