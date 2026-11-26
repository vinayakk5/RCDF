"""Firm -> RM (main tender) workspace: list, per-RM summary and global search.

Everything here is read-only except set_main_tender_status / apply_extension.
Quantities are quintals (the *_mt column names are legacy).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models import (
    Bill, BillStatus, Broker, Company, Deal, Dispatch, IngestStatus, MainTender,
    PendingIngest, PlantReceipt, PlantUnloadingEntry, PurchaseBill, PurchaseOrder,
    Payment, SalesBill, SalesBillStatus, Tender,
)

RM_STATUSES = ("active", "closed", "archived")

_RM_RE = re.compile(r"(?:(?<![A-Z])|(?<=NIT))RM\s*[-_/.]?\s*(\d{2,5})(?!\d)(?:\s*([A-Z])(?![A-Z]))?", re.I)
_EXTENSION_RE = re.compile(r"extens|extention|time\s*ext|\bext\.|samay\s*vridhi|अवधि", re.I)


def rm_codes_in(text: Any) -> List[str]:
    """Every RM code mentioned in a string, normalised to RM-844 / RM-840A."""
    out: List[str] = []
    for m in _RM_RE.finditer(str(text or "")):
        code = f"RM-{m.group(1)}{(m.group(2) or '').upper()}"
        if code not in out:
            out.append(code)
    return out


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _d(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, (date, datetime)) else (str(v) if v else None)


def upload_url(path: Optional[str]) -> Optional[str]:
    """Stored paths are relative to the uploads folder, with / or \\ separators."""
    if not path:
        return None
    p = str(path).replace("\\", "/")
    i = p.lower().rfind("uploads/")
    if i != -1:
        p = p[i + len("uploads/"):]
    return "/uploads/" + p.lstrip("/")


def mt_status(mt: MainTender) -> str:
    s = (getattr(mt, "status", None) or "").strip().lower()
    if s in RM_STATUSES:
        return s
    return "active" if mt.is_active else "archived"


# ── PO money ───────────────────────────────────────────────────────────────

def po_lines(po: PurchaseOrder) -> List[dict]:
    return [x for x in (po.line_items or []) if isinstance(x, dict)]


def po_our_figures(po: PurchaseOrder) -> Dict[str, float]:
    """Quantity and value of the PO lines approved to our firm (line_items only keeps ours)."""
    qty = amt = 0.0
    for it in po_lines(po):
        q = _f(it.get("approved_quantity_qtl") or it.get("quantity_qtl"))
        r = _f(it.get("approved_rate_per_qtl") or it.get("rate_per_qtl"))
        qty += q
        amt += q * r if (q and r) else _f(it.get("line_amount"))
    return {"our_qty_qtl": round(qty, 3), "our_amount": round(amt, 2)}


# ── RM list ────────────────────────────────────────────────────────────────

def _group(db: Session, model, ids: List[int], *cols, where: Iterable = ()) -> Dict[int, tuple]:
    if not ids:
        return {}
    q = select(model.main_tender_id, *cols).where(model.main_tender_id.in_(ids))
    for w in where:
        q = q.where(w)
    q = q.group_by(model.main_tender_id)
    return {row[0]: tuple(row[1:]) for row in db.execute(q).all()}


def _pending_docs_by_rm(db: Session, company_id: Optional[int]) -> Dict[str, Dict[str, int]]:
    """Pending inbox documents per RM code (from the assigned RM or the RM read off the document)."""
    q = select(PendingIngest).where(PendingIngest.status == IngestStatus.pending)
    rows = db.execute(q.order_by(PendingIngest.id.desc()).limit(3000)).scalars().all()
    codes_by_id = _mt_codes(db)
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in rows:
        cid = p.assigned_company_id or p.company_id
        if company_id and cid and cid != company_id:
            continue
        for code in pending_rm_codes(p, codes_by_id):
            out[code][p.document_type.value if p.document_type else "not_classified"] += 1
    return out


def _mt_codes(db: Session) -> Dict[int, str]:
    return {i: c for i, c in db.execute(select(MainTender.id, MainTender.tender_code)).all()}


def pending_rm_codes(p: PendingIngest, codes_by_id: Dict[int, str]) -> List[str]:
    mid = p.assigned_main_tender_id or p.main_tender_id
    if mid and codes_by_id.get(mid):
        return [str(codes_by_id[mid]).upper()]
    payload = p.extracted_payload if isinstance(p.extracted_payload, dict) else {}
    hints = [payload.get(k) for k in ("tender_rm_number", "rm_number", "tender_number", "subject", "email_subject")]
    hints.append(p.file_name)
    codes: List[str] = []
    for h in hints:
        for c in rm_codes_in(h):
            if c not in codes:
                codes.append(c)
    return codes


def list_rms(db: Session, company_id: Optional[int] = None, status: Optional[str] = "active",
             q: Optional[str] = None, date_from: Optional[date] = None, date_to: Optional[date] = None) -> List[dict]:
    query = select(MainTender)
    if company_id:
        query = query.where(MainTender.company_id == company_id)
    mts = db.execute(query).scalars().all()
    status = (status or "active").lower()
    if status != "all":
        mts = [m for m in mts if mt_status(m) == status]
    ids = [m.id for m in mts]

    t_rows = db.execute(select(Tender).where(Tender.main_tender_id.in_(ids))).scalars().all() if ids else []
    tenders_by_mt: Dict[int, List[Tender]] = defaultdict(list)
    for t in t_rows:
        tenders_by_mt[t.main_tender_id].append(t)

    po_rows = db.execute(select(PurchaseOrder).where(PurchaseOrder.main_tender_id.in_(ids))).scalars().all() if ids else []
    pos_by_mt: Dict[int, List[PurchaseOrder]] = defaultdict(list)
    for po in po_rows:
        pos_by_mt[po.main_tender_id].append(po)

    bills = _group(db, Bill, ids, func.count(Bill.id))
    bills_open = _group(db, Bill, ids, func.count(Bill.id),
                        where=[Bill.status.in_([BillStatus.pending, BillStatus.flagged])])
    disp = _group(db, Dispatch, ids, func.count(Dispatch.id), func.sum(Dispatch.qty_mt),
                  where=[Dispatch.is_deleted == False])  # noqa: E712
    rec = _group(db, PlantReceipt, ids, func.count(PlantReceipt.id), func.sum(PlantReceipt.accepted_mt),
                 func.sum(PlantReceipt.rejected_mt), where=[PlantReceipt.is_deleted == False])  # noqa: E712
    unl = _group(db, PlantUnloadingEntry, ids, func.count(PlantUnloadingEntry.id))
    pb = _group(db, PurchaseBill, ids, func.count(PurchaseBill.id), func.sum(PurchaseBill.total_amount),
                func.sum(PurchaseBill.paid_amount))
    sb = _group(db, SalesBill, ids, func.count(SalesBill.id), func.sum(SalesBill.total_amount),
                where=[SalesBill.status != SalesBillStatus.cancelled])
    pending = _pending_docs_by_rm(db, company_id)
    companies = {c.id: c.name for c in db.execute(select(Company)).scalars().all()}

    out = []
    today = date.today()
    for m in mts:
        ts = tenders_by_mt.get(m.id, [])
        starts = [t.supply_start for t in ts if t.supply_start]
        ends = [t.supply_end or t.week2_deadline for t in ts if (t.supply_end or t.week2_deadline)]
        start, end = (min(starts) if starts else None), (max(ends) if ends else None)
        if date_from and end and end < date_from:
            continue
        if date_to and start and start > date_to:
            continue
        plants = sorted({t.plant.name for t in ts if t.plant})
        materials = sorted({t.material.name for t in ts if t.material})
        pos = pos_by_mt.get(m.id, [])
        our_amount = sum(po_our_figures(p)["our_amount"] for p in pos)
        tender_qty = sum(_f(t.tender_mt) for t in ts)
        d = disp.get(m.id, (0, 0))
        r = rec.get(m.id, (0, 0, 0))
        p = pb.get(m.id, (0, 0, 0))
        s = sb.get(m.id, (0, 0))
        pend = pending.get(str(m.tender_code).upper(), {})
        row = {
            "id": m.id,
            "company_id": m.company_id,
            "company": companies.get(m.company_id),
            "tender_code": m.tender_code,
            "title": m.title,
            "status": mt_status(m),
            "supply_start": _d(start),
            "supply_end": _d(end),
            "supply_over": bool(end and end < today),
            "days_left": (end - today).days if end else None,
            "plants": plants,
            "materials": materials,
            "subtenders": len(ts),
            "tender_qty_qtl": round(tender_qty, 3),
            "po_count": len(pos),
            "po_amount": round(our_amount, 2),
            "bills": int(bills.get(m.id, (0,))[0] or 0),
            "bills_to_check": int(bills_open.get(m.id, (0,))[0] or 0),
            "dispatches": int(d[0] or 0),
            "dispatched_qtl": round(_f(d[1]), 3),
            "receipts": int(r[0] or 0),
            "accepted_qtl": round(_f(r[1]), 3),
            "rejected_qtl": round(_f(r[2]), 3),
            "unloading_rows": int(unl.get(m.id, (0,))[0] or 0),
            "purchase_bills": int(p[0] or 0),
            "purchase_amount": round(_f(p[1]), 2),
            "paid_amount": round(_f(p[2]), 2),
            "to_pay": round(max(_f(p[1]) - _f(p[2]), 0), 2),
            "sales_bills": int(s[0] or 0),
            "sales_amount": round(_f(s[1]), 2),
            "pending_docs": int(sum(pend.values())),
            "pending_docs_by_type": dict(pend),
            "created_at": _d(m.created_at),
        }
        row["progress_pct"] = round(100 * row["accepted_qtl"] / tender_qty, 1) if tender_qty else 0
        if q:
            hay = " ".join(str(x) for x in [m.tender_code, m.title, row["company"], *plants, *materials,
                                              *[po.po_number for po in pos]]).lower()
            if not all(tok in hay for tok in q.lower().split()):
                continue
        out.append(row)

    out.sort(key=lambda r: (r["supply_end"] or "", r["created_at"] or ""), reverse=True)
    return out


def inbox_only_rms(db: Session, company_id: Optional[int] = None) -> List[dict]:
    """RM codes that inbox documents mention but that have no RM in the app yet
    (e.g. a tender notice or extension arrived, but no PO has been approved)."""
    known = {str(c).upper() for c in db.execute(select(MainTender.tender_code)).scalars().all()}
    out = []
    for code, by_type in _pending_docs_by_rm(db, company_id).items():
        if code in known:
            continue
        out.append({"tender_code": code, "pending_docs": int(sum(by_type.values())), "pending_docs_by_type": dict(by_type)})
    out.sort(key=lambda r: r["tender_code"], reverse=True)
    return out


def rm_counts(db: Session, company_id: Optional[int] = None) -> Dict[str, int]:
    query = select(MainTender)
    if company_id:
        query = query.where(MainTender.company_id == company_id)
    c = {s: 0 for s in RM_STATUSES}
    for m in db.execute(query).scalars().all():
        c[mt_status(m)] += 1
    c["all"] = sum(c.values())
    return c


# ── One RM ─────────────────────────────────────────────────────────────────

def po_to_dict(po: PurchaseOrder) -> dict:
    fig = po_our_figures(po)
    return {
        "id": po.id,
        "po_number": po.po_number,
        "po_date": _d(po.po_date),
        "plant_name": po.plant_name,
        "status": po.status.value if po.status else None,
        "buyer_name": po.buyer_name,
        "lines": po_lines(po),
        "document_total": _f(po.total_amount) if po.total_amount is not None else None,
        **fig,
        "doc_url": upload_url(po.source_doc_path),
        "source_pending_id": po.source_pending_id,
        "created_at": _d(po.created_at),
    }


def extension_info(p: PendingIngest) -> Optional[dict]:
    """If an inbox document is a tender time-extension order, return what it says."""
    payload = p.extracted_payload if isinstance(p.extracted_payload, dict) else {}
    text = " ".join(str(x) for x in [p.file_name, payload.get("subject"), payload.get("email_subject"),
                                     payload.get("document_title"), payload.get("notes"), payload.get("summary")])
    if not _EXTENSION_RE.search(text):
        return None
    new_end = None
    for k in ("extended_till", "extended_upto", "extension_end_date", "new_end_date", "new_supply_end",
              "supply_period_end", "end_date", "valid_till", "delivery_period_end"):
        v = payload.get(k)
        if v:
            dv = _parse_date(v)
            if dv and (new_end is None or dv > new_end):
                new_end = dv
    return {"new_end_date": _d(new_end), "plant_name": payload.get("plant_name") or payload.get("destination_plant")}


def _parse_date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def pending_doc_to_dict(p: PendingIngest) -> dict:
    payload = p.extracted_payload if isinstance(p.extracted_payload, dict) else {}
    ext = extension_info(p)
    return {
        "id": p.id,
        "document_type": "tender_extension" if ext else (p.document_type.value if p.document_type else None),
        "classified_as": p.document_type.value if p.document_type else None,
        "status": p.status.value if p.status else None,
        "file_name": p.file_name,
        "source": p.source.value if p.source else None,
        "source_address": p.source_address,
        "created_at": _d(p.created_at),
        "doc_url": upload_url(p.file_path),
        "extension": ext,
        "plant_name": payload.get("plant_name") or payload.get("destination_plant"),
        "vehicle_number": payload.get("vehicle_number") or payload.get("truck_number"),
        "bill_number": payload.get("bill_number"),
        "action_error": p.action_error,
    }


def rm_documents(db: Session, mt: MainTender, include_done: bool = False) -> List[dict]:
    codes_by_id = _mt_codes(db)
    code = str(mt.tender_code).upper()
    q = select(PendingIngest).order_by(PendingIngest.id.desc()).limit(3000)
    if not include_done:
        q = q.where(PendingIngest.status == IngestStatus.pending)
    out = []
    for p in db.execute(q).scalars().all():
        cid = p.assigned_company_id or p.company_id
        if cid and cid != mt.company_id:
            continue
        if code in pending_rm_codes(p, codes_by_id):
            out.append(pending_doc_to_dict(p))
    return out


def rm_summary(db: Session, mt: MainTender) -> dict:
    row = next((r for r in list_rms(db, company_id=mt.company_id, status="all") if r["id"] == mt.id), None) or {}
    tenders = db.execute(select(Tender).where(Tender.main_tender_id == mt.id).order_by(Tender.id)).scalars().all()
    deals = db.execute(select(Deal).where(Deal.main_tender_id == mt.id).order_by(Deal.id)).scalars().all()
    pos = db.execute(select(PurchaseOrder).where(PurchaseOrder.main_tender_id == mt.id)
                     .order_by(PurchaseOrder.po_date, PurchaseOrder.id)).scalars().all()

    acc = defaultdict(float)
    rej = defaultdict(float)
    for tid, a, r in db.execute(select(PlantReceipt.tender_id, func.sum(PlantReceipt.accepted_mt),
                                       func.sum(PlantReceipt.rejected_mt))
                                .where(PlantReceipt.main_tender_id == mt.id, PlantReceipt.is_deleted == False)  # noqa: E712
                                .group_by(PlantReceipt.tender_id)).all():
        acc[tid], rej[tid] = _f(a), _f(r)
    disp = defaultdict(float)
    for tid, qv in db.execute(select(Dispatch.tender_id, func.sum(Dispatch.qty_mt))
                              .where(Dispatch.main_tender_id == mt.id, Dispatch.is_deleted == False)  # noqa: E712
                              .group_by(Dispatch.tender_id)).all():
        disp[tid] = _f(qv)

    po_by_id = {p.id: p for p in pos}
    sub = []
    for t in tenders:
        po = po_by_id.get(t.purchase_order_id) if t.purchase_order_id else None
        sub.append({
            "id": t.id,
            "tender_number": t.tender_number,
            "plant": t.plant.name if t.plant else None,
            "material": t.material.name if t.material else None,
            "qty_qtl": _f(t.tender_mt),
            "sale_rate_per_qtl": _f(t.sale_rate_per_qtl) or None,
            "supply_start": _d(t.supply_start),
            "supply_end": _d(t.supply_end or t.week2_deadline),
            "status": t.status.value if t.status else None,
            "po_number": po.po_number if po else None,
            "dispatched_qtl": round(disp.get(t.id, 0), 3),
            "accepted_qtl": round(acc.get(t.id, 0), 3),
            "rejected_qtl": round(rej.get(t.id, 0), 3),
            "balance_qtl": round(_f(t.tender_mt) - acc.get(t.id, 0), 3),
        })

    same_code = db.execute(select(MainTender).where(MainTender.tender_code == mt.tender_code,
                                                    MainTender.id != mt.id)).scalars().all()
    companies = {c.id: c.name for c in db.execute(select(Company)).scalars().all()}
    return {
        **row,
        "id": mt.id,
        "tender_code": mt.tender_code,
        "title": mt.title,
        "notes": mt.notes,
        "status": mt_status(mt),
        "company_id": mt.company_id,
        "company": companies.get(mt.company_id),
        "closed_at": _d(getattr(mt, "closed_at", None)),
        "subtender_rows": sub,
        "purchase_orders": [po_to_dict(p) for p in pos],
        "deals": [{
            "id": d.id, "deal_number": d.deal_number, "broker": d.broker.name if d.broker else None,
            "tender_id": d.tender_id, "material": d.material.name if d.material else None,
            "deal_qty_qtl": _f(d.deal_mt), "rate_per_qtl": _f(d.rate_per_mt),
            "dispatched_qtl": _f(d.dispatched_mt), "accepted_qtl": _f(d.accepted_mt),
            "rejected_qtl": _f(d.rejected_mt), "status": d.status.value if d.status else None,
        } for d in deals],
        "same_rm_other_firms": [{"id": o.id, "company_id": o.company_id, "company": companies.get(o.company_id)}
                                for o in same_code],
    }


def set_main_tender_status(db: Session, mt: MainTender, status: str) -> MainTender:
    status = (status or "").strip().lower()
    if status not in RM_STATUSES:
        raise ValueError(f"status must be one of {', '.join(RM_STATUSES)}")
    mt.status = status
    mt.is_active = status != "archived"
    mt.closed_at = datetime.now() if status in ("closed", "archived") else None
    db.commit()
    db.refresh(mt)
    return mt


def apply_extension(db: Session, mt: MainTender, new_end: date, plant_id: Optional[int] = None) -> List[dict]:
    """Move the supply end date of this RM's sub-tenders (optionally one plant). Never shortens."""
    q = select(Tender).where(Tender.main_tender_id == mt.id)
    if plant_id:
        q = q.where(Tender.plant_id == plant_id)
    changed = []
    for t in db.execute(q).scalars().all():
        old = t.supply_end or t.week2_deadline
        if old and new_end <= old:
            continue
        t.supply_end = new_end
        t.week2_deadline = new_end
        note = f"Supply extended {old} -> {new_end}"
        t.notes = f"{t.notes}\n{note}" if t.notes else note
        changed.append({"tender_id": t.id, "tender_number": t.tender_number, "from": _d(old), "to": _d(new_end)})
    db.commit()
    return changed


# ── Global search ──────────────────────────────────────────────────────────

def search(db: Session, q: str, company_id: Optional[int] = None, limit: int = 8) -> Dict[str, List[dict]]:
    q = (q or "").strip()
    if len(q) < 2:
        return {}
    like = f"%{q}%"
    vehicle_like = "%" + re.sub(r"[\s-]+", "%", q) + "%"
    mt_codes = _mt_codes(db)
    res: Dict[str, List[dict]] = {}

    def scoped(query, model):
        if company_id and hasattr(model, "company_id"):
            query = query.where(model.company_id == company_id)
        return query

    def run(name, fn):
        try:
            rows = fn()
            if rows:
                res[name] = rows
        except Exception as e:  # one bad section must never break the whole search
            db.rollback()
            res.setdefault("_errors", []).append({"section": name, "error": str(e)[:200]})

    rm_like = like
    codes = rm_codes_in(q)
    if not codes and re.fullmatch(r"\d{3,5}[A-Za-z]?", q):
        codes = rm_codes_in("RM " + q)
    if codes:
        rm_like = f"%{codes[0]}%"

    run("rms", lambda: [{
        "id": m.id, "label": m.tender_code, "sub": m.title, "company_id": m.company_id,
        "status": mt_status(m), "main_tender_id": m.id,
    } for m in db.execute(scoped(select(MainTender), MainTender)
                          .where(or_(MainTender.tender_code.ilike(rm_like), MainTender.title.ilike(like)))
                          .limit(limit)).scalars().all()])

    run("subtenders", lambda: [{
        "id": t.id, "label": t.tender_number, "sub": f"{t.tender_mt} qtl", "company_id": t.company_id,
        "main_tender_id": t.main_tender_id,
    } for t in db.execute(scoped(select(Tender), Tender).where(Tender.tender_number.ilike(like))
                          .limit(limit)).scalars().all()])

    run("purchase_orders", lambda: [{
        "id": p.id, "label": f"PO {p.po_number}", "sub": " · ".join(x for x in [p.plant_name, mt_codes.get(p.main_tender_id)] if x),
        "company_id": p.company_id, "main_tender_id": p.main_tender_id,
    } for p in db.execute(scoped(select(PurchaseOrder), PurchaseOrder)
                          .where(or_(PurchaseOrder.po_number.ilike(like), PurchaseOrder.plant_name.ilike(like)))
                          .order_by(PurchaseOrder.id.desc()).limit(limit)).scalars().all()])

    run("bills", lambda: [{
        "id": b.id, "label": f"Bill {b.bill_number or '#' + str(b.id)}",
        "sub": " · ".join(x for x in [b.broker_name, b.vehicle_number, _d(b.bill_date), mt_codes.get(b.main_tender_id)] if x),
        "company_id": b.company_id, "main_tender_id": b.main_tender_id, "status": b.status.value if b.status else None,
    } for b in db.execute(scoped(select(Bill), Bill)
                          .where(or_(Bill.bill_number.ilike(like), Bill.vehicle_number.ilike(vehicle_like),
                                     Bill.broker_name.ilike(like)))
                          .order_by(Bill.id.desc()).limit(limit)).scalars().all()])

    run("trucks", lambda: [{
        "id": d.id, "label": d.vehicle_number, "sub": " · ".join(x for x in [
            f"dispatch {_d(d.dispatch_date)}", f"{_f(d.qty_mt)} qtl", mt_codes.get(d.main_tender_id)] if x),
        "company_id": d.company_id, "main_tender_id": d.main_tender_id,
    } for d in db.execute(scoped(select(Dispatch), Dispatch)
                          .where(Dispatch.is_deleted == False, Dispatch.vehicle_number.ilike(vehicle_like))  # noqa: E712
                          .order_by(Dispatch.id.desc()).limit(limit)).scalars().all()])

    run("unloading", lambda: [{
        "id": e.id, "label": e.truck_number, "sub": " · ".join(x for x in [
            f"unloaded {_d(e.entry_date)}", f"WS {e.ws_no}" if e.ws_no else None, f"{_f(e.net_qty_mt)} qtl",
            mt_codes.get(e.main_tender_id)] if x),
        "company_id": e.company_id, "main_tender_id": e.main_tender_id,
    } for e in db.execute(scoped(select(PlantUnloadingEntry), PlantUnloadingEntry)
                          .where(or_(PlantUnloadingEntry.truck_number.ilike(vehicle_like),
                                     PlantUnloadingEntry.ws_no.ilike(like)))
                          .order_by(PlantUnloadingEntry.id.desc()).limit(limit)).scalars().all()])

    run("purchase_bills", lambda: [{
        "id": p.id, "label": p.pb_number or f"PB #{p.id}", "sub": f"₹{_f(p.total_amount):,.0f}",
        "company_id": p.company_id, "main_tender_id": p.main_tender_id,
    } for p in db.execute(scoped(select(PurchaseBill), PurchaseBill).where(PurchaseBill.pb_number.ilike(like))
                          .limit(limit)).scalars().all()])

    run("sales_bills", lambda: [{
        "id": s.id, "label": s.sb_number or f"SB #{s.id}", "sub": f"₹{_f(s.total_amount):,.0f}",
        "company_id": s.company_id, "main_tender_id": s.main_tender_id,
    } for s in db.execute(scoped(select(SalesBill), SalesBill).where(SalesBill.sb_number.ilike(like))
                          .limit(limit)).scalars().all()])

    run("brokers", lambda: [{
        "id": b.id, "label": b.name, "sub": getattr(b, "phone", None) or getattr(b, "gstin", None),
    } for b in db.execute(select(Broker).where(Broker.name.ilike(like)).limit(limit)).scalars().all()])

    def docs():
        out = []
        qq = select(PendingIngest).where(PendingIngest.status == IngestStatus.pending)
        if codes:
            rows = db.execute(qq.order_by(PendingIngest.id.desc()).limit(3000)).scalars().all()
            rows = [p for p in rows if codes[0] in pending_rm_codes(p, mt_codes)]
        else:
            rows = db.execute(qq.where(PendingIngest.file_name.ilike(like))
                              .order_by(PendingIngest.id.desc()).limit(limit)).scalars().all()
        for p in rows[:limit]:
            d = pending_doc_to_dict(p)
            out.append({"id": p.id, "label": p.file_name, "sub": f"{d['document_type']} · waiting for review",
                        "company_id": p.assigned_company_id or p.company_id})
        return out
    run("documents", docs)
    return res
