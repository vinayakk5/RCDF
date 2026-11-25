"""Double-check readings of plant unloading registers, tender notices and POs.

Same idea as bill_verifier: two independent free AI readers read the same page,
then plain code compares them and runs arithmetic checks. Nothing is trusted just
because a model said so. A row/field is "verified" only when both readers agree
(or one reading is confirmed by the sheet's own arithmetic).

Units: everything is quintals (Qtl). Plant weighbridge sheets are often in Kg;
a per-truck figure above MAX_TRUCK_QTL is treated as Kg and divided by 100.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from services.bill_verifier import norm_vehicle, to_number, vehicle_format_ok

MAX_TRUCK_QTL = 700.0      # a truck carries ~100-450 qtl; anything above 700 is a unit error
MIN_TRUCK_QTL = 5.0
QTY_TOL_QTL = 0.6          # readers may round differently by a few kg
BAG_QTL_RANGE = (0.25, 1.05)  # 25-105 kg per bag

VERIFIED_ROW = {"verified", "confirmed_by_total"}


def _q(v) -> Optional[float]:
    n = to_number(v)
    return round(n, 3) if n is not None else None


def _kg_fix(v: Optional[float]) -> Tuple[Optional[float], bool]:
    if v is None:
        return None, False
    if v > MAX_TRUCK_QTL and v / 100.0 >= MIN_TRUCK_QTL:
        return round(v / 100.0, 3), True
    return v, False


def _row_norm(r: dict) -> dict:
    """Pull one reader's row into a comparable shape (quintals)."""
    notes = []
    net = _q(r.get("net_qty_mt"))
    rec = _q(r.get("received_qty_mt"))
    gross_kg = _q(r.get("gross_weight_kg"))
    tare_kg = _q(r.get("tare_weight_kg"))
    net_kg = _q(r.get("net_weight_kg"))
    if net is None and net_kg is not None:
        net = round(net_kg / 100.0, 3)
        notes.append("net taken from the Kg column")
    net, fixed = _kg_fix(net)
    if fixed:
        notes.append("net read as Kg and converted to quintals")
    rec, fixed_r = _kg_fix(rec)
    if fixed_r:
        notes.append("received read as Kg and converted to quintals")
    return {
        "truck": norm_vehicle(r.get("truck_number")),
        "ws_no": re.sub(r"\W+", "", str(r.get("ws_no") or "")).upper() or None,
        "date": str(r.get("date") or "") or None,
        "net": net,
        "received": rec,
        "total": _q(r.get("total_qty_mt")),
        "bags": to_number(r.get("no_of_bags")),
        "gross_kg": gross_kg,
        "tare_kg": tare_kg,
        "net_kg": net_kg,
        "notes": notes,
    }


def _same_qty(a: Optional[float], b: Optional[float]) -> bool:
    return a is not None and b is not None and abs(a - b) <= QTY_TOL_QTL


def _row_checks(n: dict, prev_total: Optional[float]) -> Tuple[Dict[str, Optional[bool]], List[str]]:
    checks: Dict[str, Optional[bool]] = {}
    reasons: List[str] = []
    checks["truck_format"] = vehicle_format_ok(n["truck"]) if n["truck"] else False
    if not checks["truck_format"]:
        reasons.append(f"truck number '{n['truck'] or '?'}' is not a valid registration")
    net = n["net"]
    checks["net_present"] = net is not None
    if net is None:
        reasons.append("net quantity not read")
    else:
        checks["net_plausible"] = MIN_TRUCK_QTL <= net <= MAX_TRUCK_QTL
        if not checks["net_plausible"]:
            reasons.append(f"net {net:g} qtl is not a believable truck load")
    if net is not None and n["received"] is not None:
        checks["net_le_received"] = net <= n["received"] + 0.01
        if not checks["net_le_received"]:
            reasons.append(f"net {net:g} is more than received {n['received']:g}")
    if n["gross_kg"] is not None and n["tare_kg"] is not None and (n["net_kg"] is not None or net is not None):
        net_kg = n["net_kg"] if n["net_kg"] is not None else net * 100
        checks["gross_minus_tare"] = abs((n["gross_kg"] - n["tare_kg"]) - net_kg) <= 20
        if not checks["gross_minus_tare"]:
            reasons.append(f"gross {n['gross_kg']:g} - tare {n['tare_kg']:g} kg does not equal net {net_kg:g} kg")
    if net is not None and n["bags"]:
        per_bag = net / n["bags"]
        checks["bag_weight"] = BAG_QTL_RANGE[0] <= per_bag <= BAG_QTL_RANGE[1]
        if not checks["bag_weight"]:
            reasons.append(f"{n['bags']:g} bags for {net:g} qtl is {per_bag * 100:.0f} kg a bag")
    if net is not None and prev_total is not None and n["total"] is not None:
        checks["running_total"] = abs((n["total"] - prev_total) - net) <= QTY_TOL_QTL
    return checks, reasons


def _match_rows(a_rows: List[dict], b_rows: List[dict]) -> List[Optional[int]]:
    """For each row in A, the index of the same truck trip in B (truck, then WS no, then order)."""
    used = set()
    out: List[Optional[int]] = []
    for ra in a_rows:
        pick = None
        for j, rb in enumerate(b_rows):
            if j in used:
                continue
            if ra["truck"] and ra["truck"] == rb["truck"] and (not ra["date"] or not rb["date"] or ra["date"] == rb["date"]):
                pick = j
                break
        if pick is None and ra["ws_no"]:
            for j, rb in enumerate(b_rows):
                if j not in used and rb["ws_no"] == ra["ws_no"]:
                    pick = j
                    break
        if pick is not None:
            used.add(pick)
        out.append(pick)
    return out


def verify_unloading(readings: List[Tuple[str, dict]]) -> Dict[str, Any]:
    """Compare two readings of one unloading register page, row by row.

    Returns merged rows (from the first reading, values corrected where the second
    reading plus arithmetic say so) with verify_status / verify_reasons on each.
    """
    readings = [(n, r) for n, r in readings if isinstance(r, dict) and (r.get("rows") or [])]
    if not readings:
        return {"rows": [], "needs_review": True, "review_reasons": ["No reader could read any row"],
                "readers": [], "rows_verified": 0, "rows_total": 0}
    name_a, res_a = readings[0]
    raw_a = [r for r in res_a.get("rows") or [] if isinstance(r, dict)]
    a = [_row_norm(r) for r in raw_a]
    has_second = len(readings) > 1
    b = [_row_norm(r) for r in (readings[1][1].get("rows") or []) if isinstance(r, dict)] if has_second else []
    match = _match_rows(a, b) if has_second else [None] * len(a)

    merged: List[dict] = []
    review: List[str] = []
    verified = 0
    prev_total = None
    for i, (raw, na) in enumerate(zip(raw_a, a)):
        nb = b[match[i]] if match[i] is not None else None
        reasons = list(na["notes"])
        status = "single_reader"
        net = na["net"]
        if nb is not None:
            if _same_qty(na["net"], nb["net"]):
                status = "verified"
            else:
                # Readers disagree: the sheet's running total can settle it.
                if prev_total is not None and na["total"] is not None:
                    step = round(na["total"] - prev_total, 3)
                    for cand in (na["net"], nb["net"]):
                        if cand is not None and abs(step - cand) <= QTY_TOL_QTL:
                            net = cand
                            status = "confirmed_by_total"
                            reasons.append(f"readers disagreed ({na['net']} vs {nb['net']}); running total confirms {cand:g}")
                            break
                if status != "confirmed_by_total":
                    status = "qty_conflict"
                    reasons.append(f"readers disagree on net qty: {na['net']} vs {nb['net']}")
        elif has_second:
            status = "truck_not_confirmed"
            reasons.append("second reader did not find this truck")
        else:
            reasons.append("only one reader could read this page")
        row_view = dict(na, net=net)
        checks, check_reasons = _row_checks(row_view, prev_total)
        if any(v is False for v in checks.values()):
            reasons.extend(check_reasons)
            if status in VERIFIED_ROW:
                status = "check_failed"
        elif status == "single_reader" and checks.get("running_total") is True:
            status = "confirmed_by_total"
            reasons.append("running total confirms the net qty")
        if na["total"] is not None:
            prev_total = na["total"]
        out = dict(raw)
        out["net_qty_mt"] = net
        if na["received"] is not None:
            out["received_qty_mt"] = na["received"]
        out["truck_number"] = na["truck"] or raw.get("truck_number")
        out["verify_status"] = status
        out["verify_reasons"] = reasons
        out["verify_checks"] = checks
        if status in VERIFIED_ROW:
            verified += 1
        else:
            review.append(f"{out.get('truck_number') or 'row ' + str(i + 1)}: {'; '.join(reasons) or status}")
        merged.append(out)

    if has_second:
        extra = [b[j]["truck"] for j in range(len(b)) if j not in set(x for x in match if x is not None) and b[j]["truck"]]
        if extra:
            review.append(f"second reader found trucks the first missed: {', '.join(extra)}")
    return {
        "rows": merged,
        "readers": [n for n, _ in readings],
        "rows_total": len(merged),
        "rows_verified": verified,
        "needs_review": bool(review),
        "review_reasons": review,
    }


# ── Tender notices and purchase orders ─────────────────────────────────────

def _norm_code(v) -> Optional[str]:
    s = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
    return s or None


def _norm_name(v) -> Optional[str]:
    s = re.sub(r"[^a-z]", "", str(v or "").lower())
    if s.startswith("kalader"):
        return "kaladera"
    return s or None


def _norm_date(v) -> Optional[str]:
    s = str(v or "").strip()
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def _items_map(items, rate_key: Optional[str] = None) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        k = _norm_name(it.get("material_type") or it.get("material") or it.get("item"))
        if not k:
            continue
        qty = to_number(it.get("quantity_qtl") or it.get("approved_quantity_qtl"))
        rate = to_number(it.get(rate_key)) if rate_key else None
        out[k] = (qty, rate)
    return out


def verify_header_doc(first: dict, second: Optional[dict], fields: List[Tuple[str, str]],
                      rate_key: Optional[str] = None) -> Dict[str, Any]:
    """Field-by-field agreement for tender notices / POs.

    fields: list of (key, kind) where kind is code | name | date.
    """
    second = second if isinstance(second, dict) and not second.get("error") else None
    norm = {"code": _norm_code, "name": _norm_name, "date": _norm_date}
    out_fields = {}
    reasons = []
    for key, kind in fields:
        a = norm[kind](first.get(key))
        b = norm[kind](second.get(key)) if second else None
        if a is None and b is None:
            st = "missing"
        elif second is None:
            st = "single"
        elif a == b:
            st = "agree"
        elif a is None or b is None:
            st = "single"
        else:
            st = "conflict"
        out_fields[key] = {"status": st, "value": first.get(key),
                           "other": second.get(key) if second else None}
        if st == "conflict":
            reasons.append(f"{key}: readers disagree ({first.get(key)} vs {second.get(key)})")
        elif st in ("missing", "single") and kind == "code":
            reasons.append(f"{key} not confirmed by a second reader")
    ia = _items_map(first.get("items") or first.get("line_items"), rate_key)
    ib = _items_map((second or {}).get("items") or (second or {}).get("line_items"), rate_key)
    items = {}
    for mat, (qa, ra) in ia.items():
        if second is None:
            st = "single"
        elif mat not in ib:
            st = "not_confirmed"
        else:
            qb, rb = ib[mat]
            q_ok = qa is not None and qb is not None and abs(qa - qb) <= max(0.5, 0.001 * qa)
            r_ok = (rate_key is None) or (ra is not None and rb is not None and abs(ra - rb) <= 0.5)
            st = "agree" if q_ok and r_ok else "conflict"
            if st == "conflict":
                reasons.append(f"{mat}: readers disagree (qty {qa} vs {qb}" + (f", rate {ra} vs {rb}" if rate_key else "") + ")")
        if st == "not_confirmed":
            reasons.append(f"{mat}: second reader did not find this item")
        items[mat] = st
    if second is None:
        reasons.append("only one reader could read this document")
    for mat in ib:
        if mat not in ia and second is not None:
            reasons.append(f"second reader found item {mat} the first missed")
    return {"fields": out_fields, "items": items, "needs_review": bool(reasons), "review_reasons": reasons,
            "readers": [first.get("source"), (second or {}).get("source")]}
