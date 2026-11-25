"""Phase 2: bills go to the right firm/tender/deal by BILL date, not arrival date.

Scenario from the business: tender A supplies 10-25 Nov, tender B 20-30 Nov
(overlap 20-25). A bill dated 15 Nov that arrives on 30 Nov belongs to A.
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from database import Base
import models as m
import main


class AssignCase(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        db = self.db
        self.nath = m.Company(name="Shree Nath Industries")
        self.vinayak = m.Company(name="Shree Vinayak Trading Company")
        self.ajmer = m.Plant(name="Ajmer", code="AJM")
        self.pali = m.Plant(name="Pali", code="PAL")
        self.maize = m.Material(name="Maize", code="MAIZE")
        self.domc = m.Material(name="Domc", code="DOMC")
        self.broker = m.Broker(name="Yesh Dalal")
        db.add_all([self.nath, self.vinayak, self.ajmer, self.pali, self.maize, self.domc, self.broker])
        db.flush()
        self.cycle = m.SproxxCycle(name="c", cycle_start=date(2026, 11, 1), cycle_end=date(2026, 11, 30),
                                   week1_end=date(2026, 11, 8), week2_end=date(2026, 11, 15))
        db.add(self.cycle)
        db.flush()
        self.n = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def tender(self, company, start, end, plant=None, material=None):
        self.n += 1
        mt = m.MainTender(company_id=company.id, tender_code=f"RM-{840 + self.n}")
        self.db.add(mt)
        self.db.flush()
        t = m.Tender(company_id=company.id, main_tender_id=mt.id, cycle_id=self.cycle.id,
                     tender_number=f"RM-{840 + self.n} Maize Ajmer", plant_id=(plant or self.ajmer).id,
                     material_id=(material or self.maize).id, tender_mt=4000, week1_target_mt=2000,
                     week1_deadline=start, week2_deadline=end, supply_start=start, supply_end=end)
        self.db.add(t)
        self.db.flush()
        return t

    def deal(self, t, rate=2500, qty=2000, dispatched=0):
        d = m.Deal(company_id=t.company_id, main_tender_id=t.main_tender_id, tender_id=t.id,
                   broker_id=self.broker.id, deal_number=f"D-{t.id}-{rate}", material_id=t.material_id,
                   deal_mt=qty, rate_per_mt=rate, dispatched_mt=dispatched)
        self.db.add(d)
        self.db.flush()
        return d

    def bill(self, bill_date, company=None, rate=2500, qty=300, truck="RJ01AB1234", plant=None):
        b = m.Bill(company_id=(company or self.nath).id, vehicle_number=truck, material_name="Maize",
                   qty_mt=qty, rate_per_mt=rate, total_amount=qty * rate, bill_date=bill_date,
                   bill_number=str(self.n), plant_id=(plant or self.ajmer).id, plant_name="Ajmer")
        self.db.add(b)
        self.db.flush()
        return b


class OverlapTests(AssignCase):
    def setUp(self):
        super().setUp()
        self.tA = self.tender(self.nath, date(2026, 11, 10), date(2026, 11, 25))
        self.tB = self.tender(self.nath, date(2026, 11, 20), date(2026, 11, 30))
        self.dA = self.deal(self.tA, rate=2500)
        self.dB = self.deal(self.tB, rate=2600)

    def test_bill_dated_before_overlap_goes_to_first_tender_even_if_late(self):
        b = self.bill(date(2026, 11, 15))   # arrives on 30th - arrival date is irrelevant
        deal = main._auto_assign_bill_to_deal_and_dispatch(self.db, b)
        self.assertEqual(deal.id, self.dA.id)
        self.assertEqual(b.tender_id, self.tA.id)
        self.assertEqual(b.assignment_status, "auto")

    def test_bill_after_first_tender_goes_to_second(self):
        b = self.bill(date(2026, 11, 28), rate=2600)
        self.assertEqual(main._auto_assign_bill_to_deal_and_dispatch(self.db, b).id, self.dB.id)

    def test_overlap_period_resolved_by_rate(self):
        b = self.bill(date(2026, 11, 22), rate=2600)
        self.assertEqual(main._auto_assign_bill_to_deal_and_dispatch(self.db, b).id, self.dB.id)

    def test_overlap_with_no_distinguishing_signal_goes_to_review(self):
        self.dB.rate_per_mt = 2500
        b = self.bill(date(2026, 11, 22), rate=2500)
        self.assertIsNone(main._auto_assign_bill_to_deal_and_dispatch(self.db, b))
        self.assertEqual(b.assignment_status, "ambiguous")
        self.assertEqual(len(b.assignment_candidates), 2)

    def test_late_bill_after_window_within_grace(self):
        self.dB.status = m.DealStatus.cancelled
        b = self.bill(date(2026, 12, 5))   # 10 days after tender A... B cancelled
        deal = main._auto_assign_bill_to_deal_and_dispatch(self.db, b)
        self.assertEqual(deal.id, self.dA.id)
        self.assertIn("late-bill window", b.assignment_reason)

    def test_bill_far_outside_any_window_not_assigned(self):
        b = self.bill(date(2027, 1, 20))
        self.assertIsNone(main._auto_assign_bill_to_deal_and_dispatch(self.db, b))
        self.assertEqual(b.assignment_status, "no_candidate")


class FirmAndPlantTests(AssignCase):
    def test_never_crosses_firms(self):
        t_other = self.tender(self.vinayak, date(2026, 11, 10), date(2026, 11, 25))
        self.deal(t_other)
        b = self.bill(date(2026, 11, 15), company=self.nath)
        self.assertIsNone(main._auto_assign_bill_to_deal_and_dispatch(self.db, b))

    def test_plant_filter(self):
        t_pali = self.tender(self.nath, date(2026, 11, 10), date(2026, 11, 25), plant=self.pali)
        t_ajm = self.tender(self.nath, date(2026, 11, 10), date(2026, 11, 25))
        self.deal(t_pali)
        d_ajm = self.deal(t_ajm, rate=2501)
        b = self.bill(date(2026, 11, 15))
        self.assertEqual(main._auto_assign_bill_to_deal_and_dispatch(self.db, b).id, d_ajm.id)

    def test_full_deal_loses_to_open_deal(self):
        t1 = self.tender(self.nath, date(2026, 11, 10), date(2026, 11, 25))
        t2 = self.tender(self.nath, date(2026, 11, 10), date(2026, 11, 25))
        self.deal(t1, qty=1000, dispatched=1000)
        d_open = self.deal(t2, qty=1000, dispatched=0, rate=2501)
        b = self.bill(date(2026, 11, 15))
        self.assertEqual(main._auto_assign_bill_to_deal_and_dispatch(self.db, b).id, d_open.id)


class RepeatTruckTests(AssignCase):
    def test_receipt_matches_closest_trip_of_same_truck(self):
        t = self.tender(self.nath, date(2026, 11, 1), date(2026, 11, 30))
        d = self.deal(t)
        b1 = self.bill(date(2026, 11, 3))
        main._auto_assign_bill_to_deal_and_dispatch(self.db, b1)
        b2 = self.bill(date(2026, 11, 18))
        b2.bill_number = "second"
        main._auto_assign_bill_to_deal_and_dispatch(self.db, b2)
        self.db.flush()
        data = main.ReceiptCreate(vehicle_number="RJ01AB1234", plant_id=self.ajmer.id,
                                  receipt_date=date(2026, 11, 19), accepted_mt=300, rejected_mt=0,
                                  material_id=self.maize.id)
        out = main.add_receipt(data, company_id=None, main_tender_id=None, tender_id=None, db=self.db)
        disp2 = self.db.execute(sa.select(m.Dispatch).where(m.Dispatch.bill_id == b2.id)).scalar_one()
        self.assertEqual(out["dispatch_id"], disp2.id)

    def test_receipt_months_later_does_not_match_old_dispatch(self):
        t = self.tender(self.nath, date(2026, 11, 1), date(2026, 11, 30))
        self.deal(t)
        b1 = self.bill(date(2026, 11, 3))
        main._auto_assign_bill_to_deal_and_dispatch(self.db, b1)
        self.db.flush()
        data = main.ReceiptCreate(vehicle_number="RJ01AB1234", plant_id=self.ajmer.id,
                                  receipt_date=date(2027, 1, 10), accepted_mt=300, rejected_mt=0,
                                  material_id=self.maize.id)
        out = main.add_receipt(data, company_id=None, main_tender_id=None, tender_id=None, db=self.db)
        self.assertIsNone(out["dispatch_id"])

    def test_late_bill_picks_up_existing_unloading_receipt(self):
        t = self.tender(self.nath, date(2026, 11, 1), date(2026, 11, 30))
        self.deal(t)
        data = main.ReceiptCreate(vehicle_number="RJ01AB1234", plant_id=self.ajmer.id,
                                  receipt_date=date(2026, 11, 6), accepted_mt=290, rejected_mt=10,
                                  material_id=self.maize.id)
        main.add_receipt(data, company_id=None, main_tender_id=None, tender_id=None, db=self.db)
        b = self.bill(date(2026, 11, 4))   # bill arrives after the plant result
        main._auto_assign_bill_to_deal_and_dispatch(self.db, b)
        self.db.flush()
        disp = self.db.execute(sa.select(m.Dispatch).where(m.Dispatch.bill_id == b.id)).scalar_one()
        self.assertEqual(disp.status, m.DispatchStatus.partial)


class FulfilmentTests(AssignCase):
    def test_behind_and_fulfilled_states(self):
        t = self.tender(self.nath, date(2026, 11, 1), date(2026, 11, 30))
        slow = self.deal(t, qty=2000, rate=2500)
        done = self.deal(t, qty=300, rate=2501)
        b = self.bill(date(2026, 11, 3))
        b.deal_id = done.id
        self.db.flush()
        rows = {r["deal_id"]: r for r in main._deal_fulfilment_rows(self.db, today=date(2026, 11, 20))}
        self.assertEqual(rows[done.id]["state"], "fulfilled")
        self.assertEqual(rows[slow.id]["state"], "behind")      # 0 billed, ~1300 expected by the 20th
        self.assertEqual(rows[slow.id]["remaining_qtl"], 2000)

    def test_overdue_after_supply_end(self):
        t = self.tender(self.nath, date(2026, 11, 1), date(2026, 11, 10))
        d = self.deal(t, qty=500)
        rows = main._deal_fulfilment_rows(self.db, today=date(2026, 11, 20))
        self.assertEqual(rows[0]["state"], "overdue")


if __name__ == "__main__":
    unittest.main()
