#!/usr/bin/env python3
"""
RCDF DD Sorter & Organiser
==========================
Accepts a single DD .zip archive (or folder) containing scanned Demand Draft PDFs/images
plus an optional Allocation/Mapping sheet (handwritten or digital), classifies & reads
all pages using free Vision LLMs (Mistral / Gemini / OpenRouter :free) with Azure OCR
fallback, reconciles DD numbers (e.g. 000861 / 861) to plants, and organizes each DD
beside its plant's BOQ in Tender_Prep_<YYYY-MM-DD>/<Plant>/.
"""

import os
import re
import io
import sys
import json
import time
import shutil
import base64
import zipfile
import argparse
import functools
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

print = functools.partial(print, flush=True)

# (Canonical Plant Name, substrings, exact whole-word/fuzzy short tokens)
PLANT_RULES = [
    ("Ajmer", ["ajmer", "ajmer dairy"], ["ajm"]),
    ("Bikaner", ["bikaner", "bikaner cfp"], ["bkn", "bik"]),
    ("Gulabpura", ["gulabpura", "gulapura", "gulab", "bhilwara", "bhilwara gulab"], ["glp"]),
    ("Jodhpur", ["jodhpur", "jodhpur cfp"], ["jdh", "jdr"]),
    ("Kaladera", ["kaladera", "kaladra", "khajera", "kaladera cfp"], ["kld"]),
    ("Lambiyakalan", ["lambiyakalan", "lampiakalan", "lambiakalan", "lambiyalam", "lambiyan", "lambiya"], ["lmb"]),
    ("Nadbai", ["nadbai", "bharatpur"], ["ndb"]),
    ("Pali", ["pali", "pali cfp"], ["pal"]),
]

CANONICAL_PLANTS = [p[0] for p in PLANT_RULES]

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _load_rcdf_env() -> None:
    """Load .env from Tender_Preparation, repo root, or backend/.env without failing if missing."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for cand in [here.parent / "backend" / ".env", here.parent / ".env", here / ".env"]:
        if cand.exists():
            load_dotenv(cand, override=False)


def match_plant_text(text: str) -> Optional[str]:
    """Resolve plant/city strings—including handwritten abbreviations & minor OCR typos—to canonical plant."""
    if not text:
        return None
    t = text.lower().strip()
    tokens = re.findall(r"[a-z]+", t)
    token_set = set(tokens)

    # 1. Exact canonical plant name match
    for plant in CANONICAL_PLANTS:
        if plant.lower() in token_set or plant.lower() in t:
            return plant

    # 2. Exact short codes (whole-token)
    for plant, _, codes in PLANT_RULES:
        for code in codes:
            if code in token_set:
                return plant

    # 3. Substring variants (e.g. bhilwara gulab, lambiyan, kaladra)
    for plant, substrings, _ in PLANT_RULES:
        for sub in substrings:
            if sub in t:
                return plant

    # 4. Fuzzy match against all known aliases (handles minor handwritten OCR noise like Madbal/Kaladry/JDRI)
    alias_pairs: List[Tuple[str, str]] = []
    for plant, substrings, codes in PLANT_RULES:
        alias_pairs.append((plant.lower(), plant))
        for s in substrings:
            if " " not in s:
                alias_pairs.append((s, plant))
        for c in codes:
            alias_pairs.append((c, plant))

    best_plant = None
    best_score = 0.0
    for tok in tokens:
        if len(tok) < 3:
            continue
        for alias, plant in alias_pairs:
            score = SequenceMatcher(None, tok, alias).ratio()
            # Slightly tighter tolerance for very short 3-char codes
            min_req = 0.66 if len(alias) <= 4 else 0.72
            if score >= min_req and score > best_score:
                best_score = score
                best_plant = plant
    return best_plant


def _norm_dd(val: Optional[str]) -> str:
    digits = re.sub(r"\D", "", str(val or ""))
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _extract_digital_pdf_text(pdf_path: Path) -> str:
    """Return embedded selectable text if present; returns '' for pure image scans."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        parts = [(p.extract_text() or "").strip() for p in reader.pages]
        return "\n".join(x for x in parts if x).strip()
    except Exception:
        return ""


def _to_jpeg_bytes(file_path: Path, max_dim: int = 1400) -> bytes:
    """Extract first page of PDF or load image and resize cleanly to JPEG bytes."""
    from PIL import Image

    ext = file_path.suffix.lower()
    raw_img_bytes: Optional[bytes] = None

    if ext == ".pdf":
        # Prefer extracting original embedded scan if single-image PDF (fast & lossless), else render via PyMuPDF
        try:
            from pypdf import PdfReader
            rd = PdfReader(str(file_path))
            if len(rd.pages) > 0 and len(rd.pages[0].images) == 1:
                raw_img_bytes = rd.pages[0].images[0].data
        except Exception:
            raw_img_bytes = None

        if raw_img_bytes is None:
            import fitz
            doc = fitz.open(str(file_path))
            pix = doc[0].get_pixmap(dpi=200)
            im = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
            im.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

        im = Image.open(io.BytesIO(raw_img_bytes)).convert("RGB")
    else:
        im = Image.open(file_path).convert("RGB")

    im.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _parse_json_loose(raw_text: str) -> Optional[dict]:
    txt = (raw_text or "").strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _build_batch_prompt(known_dds: Optional[List[str]] = None) -> str:
    plants_help = (
        "Ajmer (Ajm), Bikaner (Bik / Bkn), Gulabpura (Gulab / Bhilwara / Bhilwara Gulab / Glp), "
        "Jodhpur (Jdh / Jdr), Kaladera (Kaladra / Khajera / Kld), "
        "Lambiyakalan (Lambiyan / Lambiya), Nadbai (Ndb), Pali (Pal)"
    )
    dd_hint = ""
    if known_dds:
        dd_hint = f"\nKnown valid DD numbers physically present in this batch: {known_dds}. Use this list to resolve overwritten or ambiguous digits.\n"

    return f"""You are inspecting images from a Rajasthan Cattle Feed tender Demand Draft (DD) batch.
Each image is preceded by a tag [FILE: <filename>].

For EACH file, classify doc_type:
1) "demand_draft": an individual Bank Demand Draft scan (has Bank header, On Demand Pay, Rupees, DD. Sr.No. box, and bottom MICR line).
2) "allocation_map": a handwritten or printed sheet/table listing multiple DD numbers alongside city/plant locations.
3) "other": anything else.

Extraction rules:
- For "demand_draft":
  - "dd_sr_no": digits inside the "DD. Sr.No." box.
  - "micr_dd_number": the FIRST 6-digit number between special MICR symbols at bottom-left (e.g. "000858").
  - "amount": numeric amount if clearly readable.
  - "payee": payee name if clearly readable.
- For "allocation_map":
  - Extract every row into "mappings": {{"dd_number": "digits only", "location_text": "exact text written", "canonical_plant": "closest match from [{plants_help}]"}}.
{dd_hint}
Return ONLY valid JSON:
{{
  "results": [
    {{
      "filename": "...",
      "doc_type": "demand_draft" | "allocation_map" | "other",
      "dd_sr_no": "",
      "micr_dd_number": "",
      "amount": "",
      "payee": "",
      "mappings": [
        {{"dd_number": "", "location_text": "", "canonical_plant": ""}}
      ]
    }}
  ]
}}"""


def _call_mistral_vision(batch: List[Tuple[str, bytes]], prompt: str) -> Tuple[Optional[dict], str]:
    import requests
    api_key = (os.getenv("MISTRAL_API_KEY") or "").strip()
    if not api_key:
        return None, "MISTRAL_API_KEY not set"
    if (os.getenv("MISTRAL_ENABLED") or "true").strip().lower() in {"0", "false", "no"}:
        return None, "MISTRAL_ENABLED=false"

    env_models = [m.strip() for m in re.split(r"[\s,]+", os.getenv("MISTRAL_MODEL") or "") if m.strip()]
    candidates = [m for m in env_models if "pixtral" in m.lower()] + ["pixtral-12b-2409", "pixtral-large-latest"]
    candidates = [c for i, c in enumerate(candidates) if c not in candidates[:i]]

    content = [{"type": "text", "text": prompt}]
    for fname, jpg_bytes in batch:
        b64 = base64.b64encode(jpg_bytes).decode("ascii")
        content.append({"type": "text", "text": f"[FILE: {fname}]"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    last_err = ""
    for mod in candidates:
        try:
            r = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": mod,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"]["content"]
                parsed = _parse_json_loose(msg)
                if isinstance(parsed, dict) and parsed.get("results"):
                    return parsed, f"mistral:{mod}"
                last_err = f"{mod}: invalid JSON"
            else:
                last_err = f"{mod} HTTP {r.status_code}: {r.text[:160]}"
        except Exception as e:
            last_err = f"{mod}: {e}"
    return None, last_err


def _call_gemini_vision(batch: List[Tuple[str, bytes]], prompt: str) -> Tuple[Optional[dict], str]:
    import requests
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None, "GEMINI_API_KEY not set"

    parts = [{"text": prompt}]
    for fname, jpg_bytes in batch:
        b64 = base64.b64encode(jpg_bytes).decode("ascii")
        parts.append({"text": f"[FILE: {fname}]"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    last_err = ""
    for mod in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
                },
                timeout=60,
            )
            if r.status_code == 200:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                parsed = _parse_json_loose(txt)
                if isinstance(parsed, dict) and parsed.get("results"):
                    return parsed, f"gemini:{mod}"
                last_err = f"{mod}: invalid JSON"
            else:
                last_err = f"{mod} HTTP {r.status_code}"
        except Exception as e:
            last_err = f"{mod}: {e}"
    return None, last_err


def _call_openrouter_free_vision(batch: List[Tuple[str, bytes]], prompt: str) -> Tuple[Optional[dict], str]:
    import requests
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return None, "OPENROUTER_API_KEY not set"

    env_models = [m.strip() for m in re.split(r"[\s,]+", os.getenv("OPENROUTER_MODEL") or "") if m.strip().endswith(":free")]
    candidates = env_models + [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "openrouter/free",
    ]
    candidates = [c for i, c in enumerate(candidates) if c not in candidates[:i]]

    content = [{"type": "text", "text": prompt + "\nReturn ONLY raw JSON."}]
    for fname, jpg_bytes in batch:
        b64 = base64.b64encode(jpg_bytes).decode("ascii")
        content.append({"type": "text", "text": f"[FILE: {fname}]"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    last_err = ""
    for mod in candidates:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": mod,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.0,
                    "max_tokens": 2500,
                },
                timeout=60,
            )
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"].get("content") or ""
                parsed = _parse_json_loose(msg)
                if isinstance(parsed, dict) and parsed.get("results"):
                    return parsed, f"openrouter:{mod}"
                last_err = f"{mod}: empty/invalid JSON"
            else:
                last_err = f"{mod} HTTP {r.status_code}"
        except Exception as e:
            last_err = f"{mod}: {e}"
    return None, last_err


def _azure_read_ocr_lines(jpg_bytes: bytes) -> List[str]:
    """Fallback to Azure Computer Vision Read API (configured in RCDF .env) if Vision LLMs fail."""
    import requests
    endpoint = (os.getenv("AZURE_OCR_ENDPOINT") or "").strip().rstrip("/")
    api_key = (os.getenv("AZURE_OCR_KEY") or "").strip()
    if not endpoint or not api_key:
        return []
    try:
        r = requests.post(
            f"{endpoint}/vision/v3.2/read/analyze",
            headers={"Ocp-Apim-Subscription-Key": api_key, "Content-Type": "application/octet-stream"},
            data=jpg_bytes,
            timeout=25,
        )
        if r.status_code != 202:
            return []
        op_url = r.headers.get("Operation-Location")
        if not op_url:
            return []
        for _ in range(15):
            time.sleep(1.0)
            res = requests.get(op_url, headers={"Ocp-Apim-Subscription-Key": api_key}, timeout=15)
            data = res.json()
            if data.get("status") == "succeeded":
                lines = []
                for page in data.get("analyzeResult", {}).get("readResults", []):
                    for ln in page.get("lines", []):
                        lines.append(ln.get("text", ""))
                return lines
            if data.get("status") == "failed":
                return []
    except Exception:
        return []
    return []


def _analyze_batch_with_vision(batch: List[Tuple[str, bytes]], known_dds: Optional[List[str]] = None) -> Tuple[List[dict], str]:
    prompt = _build_batch_prompt(known_dds)
    providers = [
        ("Mistral", _call_mistral_vision),
        ("Gemini", _call_gemini_vision),
        ("OpenRouter-Free", _call_openrouter_free_vision),
    ]
    errors = []
    for name, fn in providers:
        parsed, detail = fn(batch, prompt)
        if parsed and isinstance(parsed.get("results"), list):
            return parsed["results"], detail
        errors.append(f"{name}({detail})")

    # Final fallback: Azure Read OCR line-by-line per image
    azure_results = []
    for fname, jpg_bytes in batch:
        lines = _azure_read_ocr_lines(jpg_bytes)
        joined = "\n".join(lines)
        if not joined:
            continue
        is_dd = ("on demand pay" in joined.lower() or "dd" in joined.lower()) and bool(re.search(r"\b0\d{5}\b", joined))
        if is_dd:
            m_micr = re.search(r"\b0*(\d{3,6})\b", joined)
            azure_results.append({
                "filename": fname,
                "doc_type": "demand_draft",
                "dd_sr_no": m_micr.group(1) if m_micr else "",
                "micr_dd_number": m_micr.group(0) if m_micr else "",
                "mappings": [],
            })
        else:
            mappings = []
            for ln in lines:
                pl = match_plant_text(ln)
                nums = re.findall(r"\b0*(\d{3,8})\b", ln)
                if pl and nums:
                    mappings.append({"dd_number": nums[0], "location_text": ln, "canonical_plant": pl})
            azure_results.append({
                "filename": fname,
                "doc_type": "allocation_map" if mappings else "other",
                "mappings": mappings,
            })
    if azure_results:
        return azure_results, "azure_read_fallback"
    raise RuntimeError("All Vision/OCR engines failed: " + " | ".join(errors))


def _resolve_default_output_dir(script_dir: Path) -> Path:
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_dir = script_dir / f"Tender_Prep_{today_str}"
    if today_dir.exists():
        return today_dir
    existing = sorted(script_dir.glob("Tender_Prep_*"), reverse=True)
    if existing:
        return existing[0]
    return today_dir


def sort_dds(
    dd_source_path: str,
    dd_map_path: Optional[str] = None,
    output_base: Optional[str] = None,
    keep_original_names: bool = False,
):
    _load_rcdf_env()

    src = Path(dd_source_path)
    script_dir = Path(__file__).resolve().parent
    output_dir = Path(output_base) if output_base else _resolve_default_output_dir(script_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print(" RCDF DD ZIP / PDF Smart Sorter (Vision LLM + MICR Reconciliation)")
    print(f" DD Input Source:   {src.resolve()}")
    if dd_map_path:
        print(f" Explicit Map File: {Path(dd_map_path).resolve()}")
    print(f" Target Base Dir:   {output_dir.resolve()}")
    print("=" * 84)

    if not src.exists():
        print(f"[!] Error: Input path not found: {src}")
        return

    # 1. Gather all candidate files into a working staging dir
    temp_extract = output_dir / "_temp_dd_extract"
    if temp_extract.exists():
        shutil.rmtree(temp_extract, ignore_errors=True)
    temp_extract.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        for f in src.rglob("*"):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                shutil.copy2(f, temp_extract / f.name)
    elif src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            zf.extractall(temp_extract)
    elif src.suffix.lower() in SUPPORTED_EXTS:
        shutil.copy2(src, temp_extract / src.name)
    else:
        print(f"[!] Unsupported input type: {src.suffix}")
        shutil.rmtree(temp_extract, ignore_errors=True)
        return

    all_files = sorted(
        [f for f in temp_extract.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS],
        key=lambda x: x.name,
    )
    if dd_map_path and Path(dd_map_path).exists():
        map_p = Path(dd_map_path)
        shutil.copy2(map_p, temp_extract / f"__EXPLICIT_MAP__{map_p.name}")
        all_files.append(temp_extract / f"__EXPLICIT_MAP__{map_p.name}")

    print(f"[*] Found {len(all_files)} document(s) to inspect.")

    # 2. Check digital text first (0ms); prepare image batches for scanned PDFs/images
    digital_maps: List[Tuple[Path, str]] = []
    scanned_items: List[Tuple[Path, bytes]] = []

    for fpath in all_files:
        if fpath.suffix.lower() == ".pdf":
            txt = _extract_digital_pdf_text(fpath)
            if len(txt) >= 25:
                digital_maps.append((fpath, txt))
                continue
        scanned_items.append((fpath, _to_jpeg_bytes(fpath)))

    print(f"[*] Digital text PDFs: {len(digital_maps)} | Scanned image PDFs: {len(scanned_items)}")

    # 3. Analyze scanned documents in compact batches (up to 5 images per Vision request)
    analyzed_by_name: Dict[str, dict] = {}
    batch_size = 5
    for idx in range(0, len(scanned_items), batch_size):
        chunk = scanned_items[idx : idx + batch_size]
        batch_payload = [(p.name, jpg) for p, jpg in chunk]
        print(f"[*] Running Vision OCR batch {idx // batch_size + 1} ({len(batch_payload)} file(s))...")
        results, provider_used = _analyze_batch_with_vision(batch_payload)
        print(f"    [+] Provider succeeded: {provider_used}")
        for item in results:
            fn = str(item.get("filename") or "").strip()
            if fn:
                analyzed_by_name[fn] = item
        if idx + batch_size < len(scanned_items):
            time.sleep(1.2)

    # 4. Separate Individual DDs vs Allocation Mapping Sheets
    dd_scans: List[dict] = []
    map_files: List[Path] = []
    other_files: List[Path] = []
    raw_mappings: List[dict] = []

    for fpath, txt in digital_maps:
        found_in_page = False
        for line in txt.splitlines():
            pl = match_plant_text(line)
            nums = re.findall(r"\b0*(\d{3,8})\b", line)
            if pl and nums:
                raw_mappings.append({"dd_number": nums[0], "location_text": line.strip(), "canonical_plant": pl})
                found_in_page = True
        if found_in_page:
            map_files.append(fpath)
        else:
            other_files.append(fpath)

    for fpath, _ in scanned_items:
        info = analyzed_by_name.get(fpath.name, {})
        dtype = str(info.get("doc_type") or "").lower()
        if dtype == "allocation_map" or fpath.name.startswith("__EXPLICIT_MAP__"):
            map_files.append(fpath)
            for m in info.get("mappings") or []:
                raw_mappings.append(m)
        elif dtype == "demand_draft":
            micr = _norm_dd(info.get("micr_dd_number"))
            sr = _norm_dd(info.get("dd_sr_no"))
            norm_num = micr or sr
            dd_scans.append({
                "path": fpath,
                "norm_num": norm_num,
                "micr_raw": str(info.get("micr_dd_number") or info.get("dd_sr_no") or norm_num),
                "amount": str(info.get("amount") or ""),
                "payee": str(info.get("payee") or ""),
            })
        else:
            other_files.append(fpath)

    known_batch_dds = sorted({d["norm_num"] for d in dd_scans if d["norm_num"]})
    print(f"[+] Identified {len(dd_scans)} Demand Draft(s): {known_batch_dds}")
    print(f"[+] Identified {len(map_files)} Allocation Map sheet(s): {[p.name for p in map_files]}")

    # 5. Build DD -> Plant map (with fuzzy plant resolution + leftover 1-digit reconciliation)
    dd_to_plant: Dict[str, str] = {}
    unresolved_map_entries: List[Tuple[str, str]] = []

    for m in raw_mappings:
        norm_num = _norm_dd(m.get("dd_number"))
        loc_txt = str(m.get("location_text") or "").strip()
        cand_plant = str(m.get("canonical_plant") or "").strip()
        plant = cand_plant if cand_plant in CANONICAL_PLANTS else match_plant_text(loc_txt)
        if not plant:
            plant = match_plant_text(loc_txt)
        if not norm_num or not plant:
            continue

        if norm_num in known_batch_dds:
            dd_to_plant[norm_num] = plant
        else:
            unresolved_map_entries.append((norm_num, plant))

    # Reconcile any overwritten/noisy digit on handwritten mapping sheet against remaining physical DDs
    if unresolved_map_entries:
        unmatched_dds = [d for d in known_batch_dds if d not in dd_to_plant]
        for noisy_num, plant in unresolved_map_entries:
            best_dd = None
            best_ratio = 0.0
            for u_dd in unmatched_dds:
                ratio = SequenceMatcher(None, noisy_num, u_dd).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_dd = u_dd
            if best_dd and (best_ratio >= 0.65 or len(unmatched_dds) == 1):
                print(f"    [~] Reconciled handwritten '{noisy_num}' -> actual DD '{best_dd}' ({plant})")
                dd_to_plant[best_dd] = plant
                unmatched_dds.remove(best_dd)

    # 6. Copy sorted DDs directly into plant folders
    matched_records = []
    unmatched_records = []

    for d in dd_scans:
        fpath: Path = d["path"]
        norm_num = d["norm_num"]
        plant = dd_to_plant.get(norm_num)
        ext_clean = fpath.suffix.lower()
        if plant:
            plant_dir = output_dir / plant
            plant_dir.mkdir(parents=True, exist_ok=True)
            safe_num = re.sub(r"[^0-9]", "", norm_num)
            safe_plant = re.sub(r"[^A-Za-z0-9]", "", plant)
            if keep_original_names:
                safe_stem = re.sub(r"[^A-Za-z0-9]", "", fpath.stem) or f"DD{safe_num}{safe_plant}"
                out_name = f"{safe_stem}{ext_clean}"
            else:
                # Strictly alphanumeric (no spaces, underscores, hyphens, or special chars) for eProc portal upload
                out_name = f"DD{safe_num}{safe_plant}{ext_clean}"
            dest = plant_dir / out_name
            shutil.copy2(fpath, dest)
            matched_records.append({
                "orig": fpath.name,
                "saved_as": out_name,
                "dd_num": norm_num,
                "plant": plant,
                "amount": d["amount"],
                "path": str(dest),
            })
        else:
            u_dir = output_dir / "DD_Unmatched"
            u_dir.mkdir(parents=True, exist_ok=True)
            safe_stem = re.sub(r"[^A-Za-z0-9]", "", fpath.stem) or "DDUnmatched"
            dest = u_dir / f"{safe_stem}{ext_clean}"
            shutil.copy2(fpath, dest)
            unmatched_records.append({"orig": fpath.name, "dd_num": norm_num or "?", "path": str(dest)})

    # Preserve mapping sheet cleanly in output root (if any)
    for idx, mp in enumerate(map_files):
        clean_name = mp.name.replace("__EXPLICIT_MAP__", "")
        suffix = mp.suffix.lower()
        target_map_name = f"DD_Allocation_Map{'' if idx == 0 else f'_{idx+1}'}{suffix}"
        shutil.copy2(mp, output_dir / target_map_name)

    for op in other_files:
        u_dir = output_dir / "DD_Unmatched"
        u_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(op, u_dir / op.name)

    shutil.rmtree(temp_extract, ignore_errors=True)

    print("\n" + "=" * 88)
    print(" DD SORTING & ORGANISATION REPORT")
    print("=" * 88)
    print(f"Total DDs Found:       {len(dd_scans)}")
    print(f"Successfully Sorted:   {len(matched_records)}")
    print(f"Unmatched Files:       {len(unmatched_records)}\n")

    if matched_records:
        print(f"{'Plant':<14} | {'DD #':<8} | {'Saved File':<24} | {'Source Scan'}")
        print("-" * 88)
        for m in sorted(matched_records, key=lambda x: x["plant"]):
            print(f"{m['plant']:<14} | {m['dd_num']:<8} | {m['saved_as']:<24} | {m['orig']}")

    if unmatched_records:
        print("\n[!] Unmatched Files (in DD_Unmatched/):")
        for u in unmatched_records:
            print(f"    - {u['orig']} (DD# {u['dd_num']})")
    print("=" * 88)
    return matched_records


def _auto_find_dd_zip(search_dir: Path) -> Optional[Path]:
    """Find the newest DD .zip archive directly in search_dir (ignoring tender work_*.zip files)."""
    candidates = [
        p for p in search_dir.glob("*.zip")
        if p.is_file() and not p.name.lower().startswith(("work_", "_temp"))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="RCDF DD Smart Sorter (Vision LLM + MICR)")
    parser.add_argument("--dd-zip", default=None, help="Path to DD .zip archive or folder (auto-detects .zip in same folder if omitted)")
    parser.add_argument("--dd-map", default=None, help="Optional separate DD allocation PDF/image")
    parser.add_argument("--output", default=None, help="Base folder where plant subfolders exist")
    parser.add_argument("--keep-names", action="store_true", help="Keep original scan stems (stripped of spaces/special chars) instead of DD<num><Plant>.pdf")
    args = parser.parse_args()

    dd_zip = args.dd_zip
    if not dd_zip:
        script_dir = Path(__file__).resolve().parent
        detected = _auto_find_dd_zip(script_dir)
        if not detected:
            print(f"[!] No DD .zip file found in: {script_dir}")
            print("    Put your DD .zip file in this same folder and double-click run_dd_sorter.bat again,")
            print('    or drag-and-drop the .zip file onto run_dd_sorter.bat.')
            sys.exit(1)
        print(f"[*] Auto-detected DD archive in folder: {detected.name}")
        dd_zip = str(detected)

    sort_dds(dd_zip, args.dd_map, args.output, keep_original_names=args.keep_names)


if __name__ == "__main__":
    main()
