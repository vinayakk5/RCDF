"""Multi-source verification for purchase bill extraction.

Free AI models misread bills in predictable ways: wrong unit (MT vs quintal vs kg),
a digit dropped from the total, a truck number guessed, a date in the wrong format.
A single model's self-reported "confidence" does not catch these.

This module takes the outputs of several independent readers (for example Gemini
vision, a second model reading the PDF text layer, and a deterministic regex parser)
and decides, field by field, which value is trustworthy:

* agreed            two or more readers give the same normalised value
* grounded          the value is literally present in the PDF text layer
* resolved_by_text  readers disagree, but exactly one value is in the PDF text
* single            only one reader has a value and it cannot be grounded
* resolved_by_math  qty/rate disagree (usually MT vs quintal), and exactly one
                    plausible combination matches the confirmed bill total
* conflict          readers disagree and the text cannot settle it
* missing           nobody found it

On top of that it runs deterministic checks (qty x rate vs amounts, GSTIN checksum,
truck number format, date sanity). The resulting confidence is computed from these
checks, never from what a model says about itself.

All quantities are QUINTALS and rates are RUPEES PER QUINTAL.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

CRITICAL_FIELDS = [
    "bill_number",
    "bill_date",
    "vehicle_number",
    "quantity_qtl",
    "rate_per_qtl",
    "total_amount",
    "vendor_name",
]
OPTIONAL_FIELDS = ["vendor_gstin", "buyer_name", "buyer_gstin", "material_type", "destination_plant", "taxable_amount"]
VERIFIED_STATUSES = {"agreed", "grounded", "resolved_by_text", "resolved_by_math"}
COMMON_GST_RATES = (0.0, 0.05, 0.12, 0.18)

# Plausible ranges for cattle-feed raw material bills (one truck).
QTY_QTL_RANGE = (5.0, 1000.0)       # 0.5 MT .. 100 MT
RATE_PER_QTL_RANGE = (300.0, 15000.0)

_VEHICLE_FULL_RE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{3,4}$")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


# ── normalisers ────────────────────────────────────────────────────────────

def to_number(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def norm_vehicle(v: Any) -> Optional[str]:
    s = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
    return s or None


def vehicle_format_ok(v: Optional[str]) -> bool:
    return bool(v and _VEHICLE_FULL_RE.match(v))


def norm_bill_number(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    if not s or s.lower() in {"null", "none", "na", "n/a"}:
        return None
    s = re.sub(r"(?i)^\s*(invoice|inv|bill|tax\s*invoice)\s*(no\.?|number)?\s*[:#\-]*\s*", "", s).strip()
    parts = [p for p in re.split(r"[/\\]+", s) if p.strip()]
    if parts:
        s = parts[-1]
    nums = re.findall(r"\d+", s)
    if nums:
        return str(int(nums[-1]))  # "01044" == "1044"
    return re.sub(r"\s+", "", s).upper() or None


def norm_date(v: Any) -> Optional[str]:
    """Return ISO yyyy-mm-dd from common Indian bill date formats, else None."""
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    s = str(v).strip()
    if not s or s.lower() in {"null", "none"}:
        return None
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_iso(y, mo, d)
    m = re.search(r"(\d{1,2})[-/. ]+([A-Za-z]{3,9})[-/., ]+(\d{2,4})", s)
    if m:
        mo = _MONTHS.get(m.group(2)[:3].lower())
        if mo:
            return _safe_iso(_year(m.group(3)), mo, int(m.group(1)))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        # India: day first.
        return _safe_iso(_year(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _year(y: str) -> int:
    yi = int(y)
    return 2000 + yi if yi < 100 else yi


def _safe_iso(y: int, mo: int, d: int) -> Optional[str]:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def norm_gstin(v: Any) -> Optional[str]:
    s = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
    return s if len(s) == 15 else None


def gstin_checksum_ok(g: Optional[str]) -> bool:
    """Official GSTIN check-digit (base-36 Luhn-style)."""
    if not g or len(g) != 15:
        return False
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(g[:14]):
        if ch not in chars:
            return False
        val = chars.index(ch) * (2 if i % 2 else 1)
        total += val // 36 + val % 36
    check = chars[(36 - total % 36) % 36]
    return check == g[14]


def norm_text_name(v: Any) -> Optional[str]:
    s = re.sub(r"[^A-Z0-9 ]", " ", str(v or "").upper())
    s = re.sub(r"\b(M\s*S|MESSRS|PVT|PRIVATE|LTD|LIMITED|CO|COMPANY|THE)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


# ── source normalisation (units) ───────────────────────────────────────────

def _unit_variants(qty: Optional[float], rate: Optional[float]) -> List[Tuple[str, Optional[float], Optional[float]]]:
    out = [("qtl", qty, rate)]
    if qty is not None or rate is not None:
        out.append(("mt", qty * 10 if qty is not None else None, rate / 10 if rate is not None else None))
        out.append(("kg", qty / 100 if qty is not None else None, rate * 100 if rate is not None else None))
        out.append(("qty_x10", qty * 10 if qty is not None else None, rate))
        out.append(("qty_div10", qty / 10 if qty is not None else None, rate))
        out.append(("rate_div10", qty, rate / 10 if rate is not None else None))
    return out


def math_fit(qty: Optional[float], rate: Optional[float], taxable: Optional[float], total: Optional[float]) -> Optional[float]:
    """Relative error of qty x rate against taxable value or GST-inclusive total (None if not checkable)."""
    if not qty or not rate:
        return None
    line = qty * rate
    if taxable:
        return abs(line - taxable) / max(taxable, 1.0)
    if total:
        return min(abs(line * (1 + g) - total) / max(total, 1.0) for g in COMMON_GST_RATES)
    return None


def canonical_qty_rate(src: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], str]:
    """Pick the unit interpretation of a reader's qty/rate that makes the bill's math work."""
    qty = to_number(src.get("quantity_qtl"))
    rate = to_number(src.get("rate_per_qtl"))
    # Prefer our own conversion of the printed value + printed unit over the
    # model's mental arithmetic.
    factor_q = {"qtl": 1.0, "quintal": 1.0, "mt": 10.0, "ton": 10.0, "kg": 0.01}
    pq, pu = to_number(src.get("quantity_printed")), re.sub(r"[^a-z]", "", str(src.get("quantity_unit_printed") or "").lower())
    for key, f in factor_q.items():
        if pq is not None and key in pu:
            qty = round(pq * f, 3)
            break
    pr, ru = to_number(src.get("rate_printed")), re.sub(r"[^a-z]", "", str(src.get("rate_unit_printed") or "").lower())
    for key, f in factor_q.items():
        if pr is not None and key in ru:
            rate = round(pr / f, 3)
            break
    if qty is None and to_number(src.get("quantity_mt")) is not None:
        qty = to_number(src.get("quantity_mt")) * 10
    if rate is None and to_number(src.get("rate_per_mt")) is not None:
        rate = to_number(src.get("rate_per_mt")) / 10
    taxable = to_number(src.get("taxable_amount") or src.get("subtotal"))
    total = to_number(src.get("total_amount"))
    if qty is None or rate is None or not (taxable or total):
        return qty, rate, "as_read"
    best = None
    for name, q, r in _unit_variants(qty, rate):
        err = math_fit(q, r, taxable, total)
        if err is None:
            continue
        if best is None or err < best[0] - 1e-9:
            best = (err, name, q, r)
    if best and best[1] != "qtl":
        base = math_fit(qty, rate, taxable, total)
        if best[0] <= 0.01 and (base is None or base > 0.02):
            return round(best[2], 3), round(best[3], 3), f"unit_fixed:{best[1]}"
    return qty, rate, "as_read"


def normalise_source(src: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(src, dict):
        return {}
    qty, rate, unit_note = canonical_qty_rate(src)
    return {
        "bill_number": norm_bill_number(src.get("bill_number") or src.get("invoice_number")),
        "bill_date": norm_date(src.get("bill_date") or src.get("invoice_date")),
        "vehicle_number": norm_vehicle(src.get("vehicle_number") or src.get("truck_number")),
        "quantity_qtl": round(qty, 3) if qty is not None else None,
        "rate_per_qtl": round(rate, 3) if rate is not None else None,
        "total_amount": to_number(src.get("total_amount")),
        "taxable_amount": to_number(src.get("taxable_amount") or src.get("subtotal")),
        "vendor_name": (str(src.get("vendor_name") or src.get("broker_name") or "").strip() or None),
        "vendor_gstin": norm_gstin(src.get("vendor_gstin") or src.get("gstin_vendor")),
        "buyer_name": (str(src.get("buyer_name") or "").strip() or None),
        "buyer_gstin": norm_gstin(src.get("buyer_gstin")),
        "material_type": (str(src.get("material_type") or "").strip() or None),
        "destination_plant": (str(src.get("destination_plant") or src.get("plant_name") or "").strip() or None),
        "_unit_note": unit_note,
    }


# ── comparison and grounding ───────────────────────────────────────────────

def same_value(field: str, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    if field in {"quantity_qtl", "rate_per_qtl", "total_amount", "taxable_amount"}:
        fa, fb = float(a), float(b)
        tol = 1.0 if field in {"total_amount", "taxable_amount"} else 0.0
        return abs(fa - fb) <= max(tol, 0.002 * max(abs(fa), abs(fb)))
    if field in {"vendor_name", "buyer_name", "destination_plant", "material_type"}:
        na, nb = norm_text_name(a), norm_text_name(b)
        if not na or not nb:
            return False
        return na == nb or SequenceMatcher(None, na, nb).ratio() >= 0.85 or na in nb or nb in na
    return str(a) == str(b)


class TextIndex:
    """Searchable forms of a PDF text layer for grounding checks."""

    def __init__(self, text: Optional[str]):
        self.raw = text or ""
        self.usable = len(self.raw.strip()) >= 60
        up = self.raw.upper()
        self.compact = re.sub(r"[^A-Z0-9]", "", up)
        self.nocomma = up.replace(",", "")
        self.names = norm_text_name(up) or ""
        self._dates: Optional[set] = None

    def dates(self) -> set:
        if self._dates is None:
            found = set()
            pat = r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/. ]+[A-Za-z]{3,9}[-/., ]+\d{2,4}"
            for m in re.finditer(pat, self.raw):
                iso = norm_date(m.group(0))
                if iso:
                    found.add(iso)
            self._dates = found
        return self._dates

    def has_number(self, value: float, decimals_ok: bool = True) -> bool:
        if value is None:
            return False
        cands = set()
        for nd in (0, 1, 2, 3):
            s = f"{value:.{nd}f}"
            if nd == 0 and abs(value - round(value)) > 1e-6:
                continue
            cands.add(s)
            if "." in s:
                cands.add(s.rstrip("0").rstrip("."))
        for c in cands:
            if re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", self.nocomma):
                return True
        return False

    def grounded(self, field: str, value: Any) -> bool:
        if not self.usable or value is None:
            return False
        if field == "bill_number":
            return bool(re.search(rf"(?<!\d)0*{re.escape(str(value))}(?!\d)", self.raw))
        if field in {"vehicle_number", "vendor_gstin", "buyer_gstin"}:
            return str(value) in self.compact
        if field == "bill_date":
            return str(value) in self.dates()
        if field in {"total_amount", "taxable_amount"}:
            return self.has_number(float(value))
        if field == "quantity_qtl":
            q = float(value)
            return any(self.has_number(x) for x in (q, q / 10, q * 100))
        if field == "rate_per_qtl":
            r = float(value)
            return any(self.has_number(x) for x in (r, r * 10, r / 100))
        if field in {"vendor_name", "buyer_name"}:
            n = norm_text_name(value)
            return bool(n and len(n) >= 4 and n in self.names)
        return False


def decide_field(field: str, values: List[Tuple[str, Any]], text: TextIndex) -> Dict[str, Any]:
    present = [(s, v) for s, v in values if v not in (None, "")]
    if not present:
        return {"value": None, "status": "missing", "sources": []}

    # Group equal values.
    groups: List[List[Tuple[str, Any]]] = []
    for s, v in present:
        for g in groups:
            if same_value(field, g[0][1], v):
                g.append((s, v))
                break
        else:
            groups.append([(s, v)])
    groups.sort(key=len, reverse=True)
    top = groups[0]
    top_grounded = text.grounded(field, top[0][1])

    if len(top) >= 2 and (len(groups) == 1 or len(top) > len(groups[1])):
        # Majority agrees. If text exists and contradicts the majority while a
        # minority value is grounded, prefer the printed value.
        if text.usable and not top_grounded and field not in {"vendor_name", "buyer_name"}:
            grounded_minor = [g for g in groups[1:] if text.grounded(field, g[0][1])]
            if len(grounded_minor) == 1:
                g = grounded_minor[0]
                return {"value": g[0][1], "status": "resolved_by_text", "sources": [s for s, _ in g],
                        "alternatives": _alts(groups, g)}
        return {"value": top[0][1], "status": "agreed", "sources": [s for s, _ in top],
                "grounded": top_grounded, "alternatives": _alts(groups, top)}

    grounded_groups = [g for g in groups if text.grounded(field, g[0][1])]
    if len(grounded_groups) == 1:
        g = grounded_groups[0]
        status = "grounded" if len(groups) == 1 else "resolved_by_text"
        return {"value": g[0][1], "status": status, "sources": [s for s, _ in g], "alternatives": _alts(groups, g)}
    if len(groups) == 1:
        return {"value": top[0][1], "status": "single", "sources": [s for s, _ in top]}
    return {"value": top[0][1], "status": "conflict", "sources": [s for s, _ in top], "alternatives": _alts(groups, top)}


def _alts(groups, chosen) -> List[Dict[str, Any]]:
    return [{"value": g[0][1], "sources": [s for s, _ in g]} for g in groups if g is not chosen]


def _plausible(qty: Optional[float], rate: Optional[float]) -> bool:
    ok = True
    if qty is not None:
        ok = ok and QTY_QTL_RANGE[0] <= qty <= QTY_QTL_RANGE[1]
    if rate is not None:
        ok = ok and RATE_PER_QTL_RANGE[0] <= rate <= RATE_PER_QTL_RANGE[1]
    return ok


def resolve_qty_rate_by_math(
    fields: Dict[str, Dict[str, Any]],
    norm: List[Tuple[str, Dict[str, Any]]],
) -> bool:
    """Settle qty/rate disagreements using the confirmed amounts.

    Readers often disagree only on unit (43.53 MT read as 43.53 "quintal", or the
    per-MT rate taken as per-quintal). Try every reader's qty and rate, plus their
    x10 / /10 unit variants, keep physically plausible pairs, and accept the result
    only when exactly one distinct pair reproduces the confirmed taxable value or
    total. Returns True when fields were updated.
    """
    amount_ok = any(
        fields[k]["status"] in {"agreed", "grounded", "resolved_by_text"} and fields[k]["value"]
        for k in ("total_amount", "taxable_amount")
    )
    if not amount_ok:
        return False
    taxable = fields["taxable_amount"]["value"] if fields["taxable_amount"]["status"] in VERIFIED_STATUSES else None
    total = fields["total_amount"]["value"] if fields["total_amount"]["status"] in VERIFIED_STATUSES else None
    qtys, rates = set(), set()
    for _, n in norm:
        q, r = n.get("quantity_qtl"), n.get("rate_per_qtl")
        if q:
            qtys.update({round(q, 3), round(q * 10, 3), round(q / 10, 3), round(q / 100, 3)})
        if r:
            rates.update({round(r, 3), round(r / 10, 3), round(r * 10, 3), round(r * 100, 3)})
    fits = []
    for q in qtys:
        for r in rates:
            if not _plausible(q, r):
                continue
            err = math_fit(q, r, taxable, total)
            if err is not None and err <= 0.006:
                fits.append((err, q, r))
    distinct = []
    for err, q, r in sorted(fits):
        if not any(abs(q - dq) <= 0.002 * dq and abs(r - dr) <= 0.002 * dr for _, dq, dr in distinct):
            distinct.append((err, q, r))
    if len(distinct) != 1:
        return False
    _, q, r = distinct[0]
    for f, val in (("quantity_qtl", q), ("rate_per_qtl", r)):
        cur = fields[f]
        if cur["value"] is not None and same_value(f, cur["value"], val) and cur["status"] in VERIFIED_STATUSES:
            continue
        fields[f] = {
            "value": val,
            "status": "resolved_by_math",
            "sources": [s for s, n in norm if n.get(f) and same_value(f, n.get(f), val)],
            "replaced": cur.get("value"),
        }
    return True


# ── main entry ─────────────────────────────────────────────────────────────

def verify_bill(
    readings: Iterable[Tuple[str, Dict[str, Any]]],
    pdf_text: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Combine independent readings of one bill into a verified result.

    readings: (source_name, raw_payload) pairs; failed readers may be passed with
    an "error" key and are ignored for voting.
    """
    today = today or date.today()
    text = TextIndex(pdf_text)
    norm: List[Tuple[str, Dict[str, Any]]] = []
    unit_notes: Dict[str, str] = {}
    failed: Dict[str, str] = {}
    for name, payload in readings:
        if not isinstance(payload, dict):
            continue
        if payload.get("error") and not any(payload.get(k) for k in ("bill_number", "total_amount", "vehicle_number")):
            failed[name] = str(payload.get("error"))[:200]
            continue
        n = normalise_source(payload)
        norm.append((name, n))
        if n.get("_unit_note") != "as_read":
            unit_notes[name] = n["_unit_note"]

    fields: Dict[str, Dict[str, Any]] = {}
    for f in CRITICAL_FIELDS + OPTIONAL_FIELDS:
        fields[f] = decide_field(f, [(s, n.get(f)) for s, n in norm], text)

    v = {f: d["value"] for f, d in fields.items()}
    pre_err = math_fit(v["quantity_qtl"], v["rate_per_qtl"], v["taxable_amount"], v["total_amount"])
    needs_math_fix = (
        fields["quantity_qtl"]["status"] not in VERIFIED_STATUSES
        or fields["rate_per_qtl"]["status"] not in VERIFIED_STATUSES
        or pre_err is None or pre_err > 0.006
        or not _plausible(v["quantity_qtl"], v["rate_per_qtl"])
    )
    if needs_math_fix and resolve_qty_rate_by_math(fields, norm):
        v = {f: d["value"] for f, d in fields.items()}
    reasons: List[str] = []

    # Deterministic checks.
    checks: Dict[str, Optional[bool]] = {}
    err = math_fit(v["quantity_qtl"], v["rate_per_qtl"], v["taxable_amount"], v["total_amount"])
    checks["math"] = None if err is None else err <= 0.006
    if checks["math"] is False:
        reasons.append(
            f"Qty × rate ({v['quantity_qtl']} × {v['rate_per_qtl']}) does not match the bill amounts"
        )
    checks["plausible_qty_rate"] = _plausible(v["quantity_qtl"], v["rate_per_qtl"]) if (v["quantity_qtl"] or v["rate_per_qtl"]) else None
    if checks["plausible_qty_rate"] is False:
        reasons.append(
            f"Quantity {v['quantity_qtl']} qtl / rate ₹{v['rate_per_qtl']} per qtl look like a unit error (MT vs quintal)"
        )
    checks["vehicle_format"] = vehicle_format_ok(v["vehicle_number"]) if v["vehicle_number"] else None
    if checks["vehicle_format"] is False:
        reasons.append(f"Truck number '{v['vehicle_number']}' is not a valid registration format")
    for g in ("vendor_gstin", "buyer_gstin"):
        if v[g]:
            checks[f"{g}_checksum"] = gstin_checksum_ok(v[g])
            if not checks[f"{g}_checksum"]:
                reasons.append(f"{g.replace('_', ' ').title()} {v[g]} fails the GSTIN check digit")
    if v["bill_date"]:
        bd = date.fromisoformat(v["bill_date"])
        checks["date_sane"] = (today - timedelta(days=180)) <= bd <= (today + timedelta(days=1))
        if not checks["date_sane"]:
            reasons.append(f"Bill date {v['bill_date']} is in the future or more than 6 months old")
    else:
        checks["date_sane"] = None

    for f in CRITICAL_FIELDS:
        st = fields[f]["status"]
        if st == "missing":
            reasons.append(f"{_label(f)} not found")
        elif st == "conflict":
            alts = ", ".join(str(a["value"]) for a in fields[f].get("alternatives", []))
            reasons.append(f"{_label(f)}: readers disagree ({fields[f]['value']} vs {alts})")
        elif st == "single":
            reasons.append(f"{_label(f)} read by only one source and not confirmed")

    verified = [f for f in CRITICAL_FIELDS if fields[f]["status"] in VERIFIED_STATUSES]
    confidence = len(verified) / len(CRITICAL_FIELDS)
    if checks["math"] is False:
        confidence *= 0.5
    elif checks["math"] is None:
        confidence *= 0.85
    if any(c is False for k, c in checks.items() if k != "math"):
        confidence *= 0.7
    if len(norm) < 2 and not text.usable:
        confidence = min(confidence, 0.6)
        reasons.append("Only one reader succeeded and there is no PDF text to confirm it")

    auto_ok = (
        len(verified) == len(CRITICAL_FIELDS)
        and checks["math"] is True
        and all(c is not False for c in checks.values())
    )

    return {
        "values": v,
        "fields": fields,
        "checks": checks,
        "confidence": round(confidence, 3),
        "auto_approve_ok": auto_ok,
        "review_reasons": reasons,
        "sources_used": [s for s, _ in norm],
        "sources_failed": failed,
        "unit_corrections": unit_notes,
        "pdf_text_used": text.usable,
    }


def _label(f: str) -> str:
    return {
        "bill_number": "Bill number",
        "bill_date": "Bill date",
        "vehicle_number": "Truck number",
        "quantity_qtl": "Quantity",
        "rate_per_qtl": "Rate",
        "total_amount": "Total amount",
        "vendor_name": "Seller name",
    }.get(f, f)
