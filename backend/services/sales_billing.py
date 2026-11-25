"""Sales bills to RCDF plants, built only from plant-unloaded (accepted) truck lines.

Rules (from the business owner):
- A sales bill quantity is the plant's net unloaded / accepted quantity, never the
  supplier's billed quantity.
- The person picks any number of unloaded lines (1 or 10) and combines them into
  one sales bill. A line can never be billed twice (unique receipt_id on
  sales_bill_lines, plus checks here with clear messages).
- The sale rate comes from the PO / tender (tender.sale_rate_per_qtl, else the PO
  line for that tender's material).
- One sales bill = one firm and one plant (Busy issues it from one firm's books to
  one plant).

All quantities are quintals; rates are Rs per quintal.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models import (
    BusyPartyMapping, Material, Plant, PlantReceipt, PurchaseOrder, SalesBill,
    SalesBillLine, SalesBillStatus, Tender,
)


class SalesBillError(ValueError):
    """A rule was broken; the message is shown to the person as is."""

    def __init__(self, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.details = details or []


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _num(v) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def next_sb_number(db: Session, when: Optional[date] = None) -> str:
    prefix = f"SB-{(when or date.today()).strftime('%y%m')}-"
    highest = 0
    for val in db.execute(select(SalesBill.sb_number).where(SalesBill.sb_number.like(f"{prefix}%"))).scalars():
        tail = str(val or "")[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:03d}"


# ── Sale rate from PO / tender ────────────────────────────────────────────

def _po_line_rate_for_tender(db: Session, t: Tender) -> Tuple[Optional[float], Optional[str]]:
    mat_name = t.material.name if t.material else None
    q = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    pos = []
    if t.purchase_order_id:
        po = db.get(PurchaseOrder, t.purchase_order_id)
        if po:
            pos.append(po)
    pos += db.execute(q.where(PurchaseOrder.tender_id == t.id)).scalars().all()
    if t.main_tender_id is not None:
        pos += db.execute(
            q.where(PurchaseOrder.main_tender_id == t.main_tender_id,
                    PurchaseOrder.company_id == t.company_id)
        ).scalars().all()
    seen = set()
    for po in pos:
        if po.id in seen:
            continue
        seen.add(po.id)
        if po.plant_id and t.plant_id and po.plant_id != t.plant_id:
            continue
        items = po.line_items if isinstance(po.line_items, list) else []
        matches = []
        for item in items:
            if not isinstance(item, dict):
                continue
            m = item.get("material_type") or item.get("material") or item.get("item")
            if mat_name and _norm(m) and (_norm(m) == _norm(mat_name) or _norm(mat_name) in _norm(m) or _norm(m) in _norm(mat_name)):
                rate = _num(item.get("approved_rate_per_qtl") or item.get("rate_per_qtl"))
                if rate and rate > 0:
                    matches.append(rate)
        # Two different rates for the same material on one PO: do not guess.
        if len(set(matches)) == 1:
            return matches[0], f"PO {po.po_number}"
    return None, None


def tender_sale_rate(db: Session, t: Optional[Tender]) -> Tuple[Optional[float], Optional[str]]:
    """Our selling rate (Rs/qtl) for a tender and where it came from."""
    if t is None:
        return None, None
    if t.sale_rate_per_qtl is not None and float(t.sale_rate_per_qtl) > 0:
        return float(t.sale_rate_per_qtl), "tender"
    return _po_line_rate_for_tender(db, t)


# ── Which unloaded lines can be billed ────────────────────────────────────

def billed_receipt_ids(db: Session, receipt_ids: Optional[Iterable[int]] = None) -> Dict[int, SalesBillLine]:
    q = select(SalesBillLine)
    if receipt_ids is not None:
        ids = list(receipt_ids)
        if not ids:
            return {}
        q = q.where(SalesBillLine.receipt_id.in_(ids))
    return {ln.receipt_id: ln for ln in db.execute(q).scalars().all()}


def _fill_lineage_from_dispatch(r: PlantReceipt) -> None:
    """Older receipts matched to our dispatch may lack firm/tender; take them from it."""
    d = r.dispatch
    if d is None:
        return
    if r.company_id is None:
        r.company_id = d.company_id
    if r.main_tender_id is None:
        r.main_tender_id = d.main_tender_id
    if r.tender_id is None and d.tender_id is not None:
        r.tender_id = d.tender_id
        r.tender = d.tender


def _receipt_line_view(db: Session, r: PlantReceipt, rate_cache: dict) -> dict:
    _fill_lineage_from_dispatch(r)
    t = r.tender
    if t is not None and t.id not in rate_cache:
        rate_cache[t.id] = tender_sale_rate(db, t)
    rate, rate_src = rate_cache.get(t.id, (None, None)) if t is not None else (None, None)
    qty = round(float(r.accepted_mt or 0), 3)
    problems = []
    if t is None:
        problems.append("not linked to a tender")
    if r.company_id is None:
        problems.append("firm unknown")
    if rate is None:
        problems.append("no sale rate on the PO/tender")
    if qty <= 0:
        problems.append("nothing accepted")
    return {
        "receipt_id": r.id,
        "company_id": r.company_id,
        "plant_id": r.plant_id,
        "plant": r.plant.name if r.plant else None,
        "tender_id": r.tender_id,
        "tender_number": t.tender_number if t else None,
        "main_tender_id": r.main_tender_id,
        "material_id": r.material_id or (t.material_id if t else None),
        "material": r.material_name or (t.material.name if t and t.material else None),
        "vehicle_number": r.vehicle_number,
        "receipt_date": str(r.receipt_date) if r.receipt_date else None,
        "rm_number": r.rm_number,
        "accepted_qtl": qty,
        "rejected_qtl": round(float(r.rejected_mt or 0), 3),
        "sale_rate_per_qtl": rate,
        "sale_rate_source": rate_src,
        "amount": round(qty * rate, 2) if rate is not None else None,
        "matched_to_our_dispatch": bool(r.dispatch_id),
        "billable": not problems,
        "problems": problems,
    }


def list_billable_lines(db: Session, company_id: Optional[int] = None, plant_id: Optional[int] = None,
                        tender_id: Optional[int] = None, main_tender_id: Optional[int] = None,
                        include_unbillable: bool = True) -> List[dict]:
    """Unloaded truck lines not yet on any sales bill (oldest first)."""
    q = (select(PlantReceipt)
         .where(PlantReceipt.is_deleted == False)  # noqa: E712
         .order_by(PlantReceipt.receipt_date, PlantReceipt.id))
    # Rows with no firm/tender yet may get it from their dispatch, so keep them in
    # the SQL filter and check again after filling.
    scope = {"company_id": company_id, "tender_id": tender_id, "main_tender_id": main_tender_id}
    for col, val in scope.items():
        if val is not None:
            c = getattr(PlantReceipt, col)
            q = q.where(or_(c == val, c == None))  # noqa: E711
    if plant_id is not None:
        q = q.where(PlantReceipt.plant_id == plant_id)
    receipts = db.execute(q).scalars().all()
    billed = billed_receipt_ids(db, [r.id for r in receipts])
    cache: dict = {}
    out = []
    for r in receipts:
        if r.id in billed:
            continue
        if float(r.accepted_mt or 0) <= 0:
            continue   # fully rejected trucks are never billed
        _fill_lineage_from_dispatch(r)
        if any(val is not None and getattr(r, col) != val for col, val in scope.items()):
            continue
        row = _receipt_line_view(db, r, cache)
        if row["billable"] or include_unbillable:
            out.append(row)
    return out


# ── Create / cancel ───────────────────────────────────────────────────────

def _busy_party_for_plant(db: Session, company_id: Optional[int], plant: Optional[Plant]) -> str:
    plant_name = plant.name if plant else "Plant"
    if company_id is not None:
        keys = {_norm(plant_name), _norm(f"RCDF {plant_name}"), _norm(f"RCDF - {plant_name}"),
                _norm(f"Cattle Feed Plant {plant_name}")}
        for m in db.execute(select(BusyPartyMapping).where(BusyPartyMapping.company_id == company_id)).scalars():
            if _norm(m.source_party_name) in keys:
                return m.busy_party_name
    return f"RCDF - {plant_name}"


def create_sales_bill(
    db: Session,
    receipt_ids: List[int],
    bill_date: Optional[date] = None,
    sb_number: Optional[str] = None,
    due_date: Optional[date] = None,
    notes: Optional[str] = None,
    created_by: Optional[str] = None,
    company_id_scope: Optional[int] = None,
) -> SalesBill:
    ids = [int(x) for x in (receipt_ids or [])]
    if not ids:
        raise SalesBillError("Pick at least one unloaded line.")
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SalesBillError(f"The same unloaded line was picked twice: {dupes}.")

    receipts = db.execute(select(PlantReceipt).where(PlantReceipt.id.in_(ids))).scalars().all()
    by_id = {r.id: r for r in receipts}
    missing = [i for i in ids if i not in by_id or by_id[i].is_deleted]
    if missing:
        raise SalesBillError(f"Unloaded lines not found (or deleted): {missing}.")

    already = billed_receipt_ids(db, ids)
    if already:
        details = [{"receipt_id": rid, "sales_bill_id": ln.sales_bill_id,
                    "sb_number": ln.sales_bill.sb_number if ln.sales_bill else None}
                   for rid, ln in already.items()]
        raise SalesBillError(
            "Some lines are already on a sales bill: "
            + ", ".join(f"truck line {d['receipt_id']} on {d['sb_number']}" for d in details),
            details,
        )

    cache: dict = {}
    views = [_receipt_line_view(db, by_id[i], cache) for i in ids]
    bad = [v for v in views if not v["billable"]]
    if bad:
        raise SalesBillError(
            "These lines cannot be billed: "
            + "; ".join(f"{v['vehicle_number']} ({', '.join(v['problems'])})" for v in bad),
            [{"receipt_id": v["receipt_id"], "problems": v["problems"]} for v in bad],
        )
    firms = {v["company_id"] for v in views}
    if len(firms) > 1:
        raise SalesBillError("Lines belong to different firms. One sales bill is for one firm.")
    plants = {v["plant_id"] for v in views}
    if len(plants) > 1:
        raise SalesBillError("Lines are for different plants. One sales bill is for one plant.")
    company_id = next(iter(firms))
    if company_id_scope is not None and company_id != company_id_scope:
        raise SalesBillError("Lines are outside the selected firm.")

    if sb_number:
        sb_number = sb_number.strip()
        if db.execute(select(SalesBill.id).where(SalesBill.sb_number == sb_number)).first():
            raise SalesBillError(f"Sales bill number {sb_number} is already used.")

    first = by_id[ids[0]]
    plant = db.get(Plant, first.plant_id)
    bdate = bill_date or date.today()
    sb = SalesBill(
        company_id=company_id,
        main_tender_id=first.main_tender_id,
        tender_id=first.tender_id,
        plant_id=first.plant_id,
        sb_number=sb_number or next_sb_number(db, bdate),
        qty_mt=0, rate_per_mt=0, total_amount=0,
        bill_date=bdate,
        due_date=due_date,
        status=SalesBillStatus.draft,
        party_name=_busy_party_for_plant(db, company_id, plant),
        notes=notes,
        created_by=created_by,
    )
    db.add(sb)
    db.flush()
    total_qty = 0.0
    total_amt = 0.0
    for v in views:
        amt = round(v["accepted_qtl"] * v["sale_rate_per_qtl"], 2)
        db.add(SalesBillLine(
            sales_bill_id=sb.id, receipt_id=v["receipt_id"], tender_id=v["tender_id"],
            material_id=v["material_id"], material_name=v["material"],
            vehicle_number=v["vehicle_number"],
            receipt_date=by_id[v["receipt_id"]].receipt_date,
            rm_number=v["rm_number"], qty_qtl=v["accepted_qtl"],
            rate_per_qtl=v["sale_rate_per_qtl"], amount=amt,
        ))
        total_qty += v["accepted_qtl"]
        total_amt += amt
    sb.qty_mt = round(total_qty, 3)
    sb.total_amount = round(total_amt, 2)
    sb.rate_per_mt = round(total_amt / total_qty, 2) if total_qty else 0
    db.flush()
    db.refresh(sb)
    return sb


def cancel_sales_bill(db: Session, sb: SalesBill) -> SalesBill:
    """Cancel and free its lines so they can go on a corrected bill."""
    if sb.status == SalesBillStatus.cancelled:
        return sb
    if sb.status == SalesBillStatus.paid:
        raise SalesBillError("A paid sales bill cannot be cancelled.")
    for ln in list(sb.lines):
        db.delete(ln)
    sb.status = SalesBillStatus.cancelled
    sb.cancelled_at = datetime.now()
    db.flush()
    return sb


def sales_bill_to_dict(sb: SalesBill, with_lines: bool = True) -> dict:
    lines = []
    changed = []
    for ln in sb.lines or []:
        r = ln.receipt
        now_qty = round(float(r.accepted_mt or 0), 3) if r is not None and not r.is_deleted else 0.0
        stale = abs(now_qty - float(ln.qty_qtl or 0)) > 0.001
        if stale:
            changed.append(ln.receipt_id)
        if with_lines:
            lines.append({
                "id": ln.id, "receipt_id": ln.receipt_id, "tender_id": ln.tender_id,
                "material": ln.material_name, "vehicle_number": ln.vehicle_number,
                "receipt_date": str(ln.receipt_date) if ln.receipt_date else None,
                "rm_number": ln.rm_number,
                "qty_qtl": float(ln.qty_qtl or 0), "rate_per_qtl": float(ln.rate_per_qtl or 0),
                "amount": float(ln.amount or 0),
                "plant_accepted_now_qtl": now_qty,
                "changed_since_billing": stale,
            })
    out = {
        "id": sb.id, "sb_number": sb.sb_number,
        "company_id": sb.company_id, "company": sb.company.name if sb.company else None,
        "main_tender_id": sb.main_tender_id,
        "plant": sb.plant.name if sb.plant else None, "plant_id": sb.plant_id,
        "tender_id": sb.tender_id,
        "party_name": sb.party_name,
        "qty_mt": float(sb.qty_mt or 0), "rate_per_mt": float(sb.rate_per_mt or 0),
        "total_amount": float(sb.total_amount or 0),
        "bill_date": str(sb.bill_date) if sb.bill_date else None,
        "due_date": str(sb.due_date) if sb.due_date else None,
        "status": sb.status.value if sb.status else None,
        "busy_exported": bool(sb.busy_exported),
        "line_count": len(sb.lines or []),
        "lines_changed_since_billing": changed,
        "notes": sb.notes,
        "created_by": sb.created_by,
    }
    if with_lines:
        out["lines"] = lines
    return out


def busy_rows_for_sales_bill(sb: SalesBill) -> List[dict]:
    """Rows in the Book1 (Busy 'Import Vouchers from Excel') layout, one per truck line.

    Same VCH/BILL_NO on several rows makes Busy build one multi-item voucher.
    """
    rows = []
    for ln in sb.lines or []:
        rows.append({
            "vch_series": "Main",
            "vch_bill_date": sb.bill_date,
            "vch_bill_no": sb.sb_number,
            "sale_purc_type": "L/GST-ItemWise",   # RCDF plants and our firms are in Rajasthan
            "party_name": sb.party_name or (f"RCDF - {sb.plant.name}" if sb.plant else "RCDF"),
            "mc_name": "Main Store",
            "item_name": ln.material_name,
            "quantity": float(ln.qty_qtl or 0),
            "unit": "QUINTAL",
            "price": float(ln.rate_per_qtl or 0),
            "itc_eligibility_type": "",
            "narration": f"Truck {ln.vehicle_number} unloaded {ln.receipt_date or ''} {ln.rm_number or ''}".strip(),
        })
    return rows
