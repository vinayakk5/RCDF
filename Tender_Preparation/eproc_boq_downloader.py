#!/usr/bin/env python3
"""
RCDF eProc Cattle Feed BOQ Downloader
=====================================
Downloads Cattle Feed Raw Material BOQ Excel files (.xls / .xlsx) from eProc Rajasthan,
prompts the on-screen CAPTCHA dialog, extracts BOQs from downloaded ZIPs,
and organizes them into city/plant folders.
"""

import os
import sys
import re
import time
import shutil
import zipfile
import argparse
import functools
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

print = functools.partial(print, flush=True)

PLANT_RULES = [
    ("Ajmer", ["ajmer"], ["ajm"]),
    ("Bikaner", ["bikaner"], ["bkn", "bik"]),
    ("Gulabpura", ["gulabpura", "gulapura"], ["glp"]),
    ("Jodhpur", ["jodhpur"], ["jdh"]),
    ("Kaladera", ["kaladera", "khajera"], ["kld"]),
    ("Lambiyakalan", ["lambiyakalan", "lampiakalan", "lambiakalan", "lambiyalam"], []),
    ("Nadbai", ["nadbai"], ["ndb"]),
    ("Pali", ["pali"], ["pal"]),
]

DEFAULT_RCDF_URL = (
    "https://eproc.rajasthan.gov.in/nicgep/app?component=%24DirectLink"
    "&page=FrontEndTendersByOrganisation&service=direct&session=T"
    "&sp=SwJvhHQ5qtWFNbxLBbm6wfg%3D%3D"
)
FALLBACK_ORG_LIST_URL = (
    "https://eproc.rajasthan.gov.in/nicgep/app?page=FrontEndTendersByOrganisation&service=page"
)

def match_plant_text(text: str) -> Optional[str]:
    if not text:
        return None
    text_clean = text.lower()
    tokens = set(re.findall(r'[a-z0-9]+', text_clean))
    for plant, _, codes in PLANT_RULES:
        for code in codes:
            if code in tokens:
                return plant
    for plant, substrings, _ in PLANT_RULES:
        for sub in substrings:
            if sub in text_clean:
                return plant
    return None

def detect_plant(title_ref: str, org_chain: str) -> str:
    plant = match_plant_text(title_ref)
    if plant:
        return plant
    plant = match_plant_text(org_chain)
    if plant:
        return plant
    return "Other_Unmatched"

def is_cattle_feed_tender(title_ref: str, org_chain: str) -> Tuple[bool, str]:
    combined = f"{title_ref} {org_chain}".lower()
    if "supply of cattle feed" in combined:
        return True, "Matches 'supply of cattle feed'"
    if "cattle feed raw material" in combined:
        return True, "Matches 'cattle feed raw material'"
    if "cattle feed plant" in combined:
        return True, "Matches 'cattle feed plant'"
    if "cfp" in combined and re.search(r'\brm\s*[-]?\s*\d+', combined):
        return True, "Matches 'cfp' + 'rm' with digits"
    return False, "Not cattle feed"

def is_retender_id(tender_id: str) -> Tuple[bool, str]:
    if not tender_id:
        return False, ""
    m = re.search(r'_(\d+)$', tender_id.strip())
    if m:
        val = int(m.group(1))
        if val > 1:
            return True, f"Re-tender suffix _{val}"
    return False, ""

def has_excluded_keywords(text: str) -> Tuple[bool, str]:
    if not text:
        return False, ""
    t = text.lower()
    phrases = [
        "re-tender", "retender", "re tender", "re-bid", "rebid",
        "2nd call", "second call", "3rd call", "third call",
        "emergency"
    ]
    for p in phrases:
        if p in t:
            return True, f"Excluded keyword '{p}'"
    if re.search(r'\bemg[.\s]|\bemg\b', t):
        return True, "Excluded keyword 'emg'"
    if re.search(r'\burgent\b', t):
        return True, "Excluded keyword 'urgent'"
    return False, ""

def is_empanelment_title(text: str) -> Tuple[bool, str]:
    if not text:
        return False, ""
    t = text.lower()
    for p in ["empanelment", "registration form"]:
        if p in t:
            return True, f"Excluded keyword '{p}'"
    return False, ""

def prompt_user_captcha_gui(city: str, tender_id: str, base64_img_data: str, current_idx: int = 1, total_count: int = 7) -> str:
    try:
        import tkinter as tk
    except ImportError:
        print("[!] tkinter not available.")
        return ""

    result = {"code": ""}
    root = tk.Tk()
    root.title(f"RCDF eProc CAPTCHA — {city} ({current_idx}/{total_count})")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    w, h = 460, 300
    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    x = max(0, (ws // 2) - (w // 2))
    y = max(0, (hs // 2) - (h // 2))
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.configure(bg="#f8f9fa")

    lbl_title = tk.Label(
        root, text=f"Download BOQ: {city.upper()} ({current_idx} of {total_count})",
        font=("Segoe UI", 12, "bold"), bg="#f8f9fa", fg="#1a202c"
    )
    lbl_title.pack(pady=(12, 2))

    lbl_sub = tk.Label(
        root, text=f"Tender ID: {tender_id}",
        font=("Segoe UI", 9), bg="#f8f9fa", fg="#718096"
    )
    lbl_sub.pack(pady=(0, 4))

    raw_b64 = base64_img_data or ""
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    # Save to captcha_images directory
    try:
        script_dir = Path(__file__).resolve().parent
        captcha_dir = script_dir / "captcha_images"
        captcha_dir.mkdir(parents=True, exist_ok=True)
        img_out = captcha_dir / f"captcha_{city.lower()}.png"
        img_out.write_bytes(base64.b64decode(raw_b64))
        print(f"[*] Saved CAPTCHA image to: {img_out}")
    except Exception as e:
        print(f"[!] Warning: Could not save image to captcha_images: {e}")

    photo = None
    if raw_b64:
        try:
            photo = tk.PhotoImage(data=raw_b64)
            lbl_img = tk.Label(root, image=photo, relief="solid", borderwidth=1, bg="#ffffff")
            lbl_img.image = photo
            lbl_img.pack(pady=4)
        except Exception:
            lbl_err = tk.Label(root, text="[CAPTCHA in browser window]", bg="#f8f9fa", fg="#e53e3e")
            lbl_err.pack(pady=4)

    lbl_prompt = tk.Label(
        root, text="Type the characters above and press Enter:",
        font=("Segoe UI", 9), bg="#f8f9fa", fg="#4a5568"
    )
    lbl_prompt.pack(pady=(4, 2))

    entry = tk.Entry(root, font=("Consolas", 14, "bold"), justify="center", width=12, relief="solid", borderwidth=1)
    entry.pack(pady=4)
    entry.focus_set()

    def on_submit(event=None):
        val = entry.get().strip()
        if val:
            result["code"] = val
            root.destroy()

    btn = tk.Button(
        root, text="Submit & Download BOQ",
        font=("Segoe UI", 10, "bold"), bg="#2b6cb0", fg="#ffffff",
        activebackground="#2c5282", activeforeground="#ffffff",
        relief="flat", padx=12, pady=4, cursor="hand2", command=on_submit
    )
    btn.pack(pady=(4, 4))

    lbl_hint = tk.Label(
        root, text="(Or you can type directly into the open browser window)",
        font=("Segoe UI", 8, "italic"), bg="#f8f9fa", fg="#a0aec0"
    )
    lbl_hint.pack(pady=(0, 6))

    root.after(120000, lambda: root.destroy())
    root.bind("<Return>", on_submit)
    root.lift()
    root.focus_force()
    entry.focus_force()

    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        sys.stdout.write('\a')
        sys.stdout.flush()

    root.mainloop()
    return result["code"]

def run_boq_downloader(portal_url: str = DEFAULT_RCDF_URL, output_base: Optional[Path] = None, headless: bool = False):
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    today_str = datetime.now().strftime("%Y-%m-%d")
    script_dir = Path(__file__).resolve().parent
    if output_base is None:
        output_dir = script_dir / f"Tender_Prep_{today_str}"
    else:
        output_dir = Path(output_base)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(" RCDF eProc BOQ Downloader & Organiser")
    print(f" Target Output Directory: {output_dir.resolve()}")
    print(f" Target Portal URL:       {portal_url}")
    print(f" Browser Mode:            {'Headless' if headless else 'Visible (Interactive)'}")
    print("=" * 80)

    downloaded_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            downloads_path=str(output_dir.resolve()),
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--start-maximized"]
        )
        context = browser.new_context(
            accept_downloads=True,
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        list_page = context.new_page()

        print("[*] Accessing Rajasthan eProc portal...")
        table_loaded = False

        if portal_url != DEFAULT_RCDF_URL:
            try:
                list_page.goto(portal_url, timeout=60000, wait_until="domcontentloaded")
                list_page.wait_for_timeout(2000)
                if list_page.locator("table#table tr").count() > 10:
                    table_loaded = True
            except Exception as e:
                print(f"[!] Direct link error: {e}")

        if not table_loaded:
            print("[*] Navigating via Organisation directory to establish fresh session...")
            list_page.goto(FALLBACK_ORG_LIST_URL, timeout=60000, wait_until="domcontentloaded")
            list_page.wait_for_timeout(2500)

            org_table = list_page.locator("table#table")
            rcdf_row = org_table.locator("tr:has-text('RCDF- MD'), tr:has-text('RCDF')")
            if rcdf_row.count() > 0:
                rcdf_link = rcdf_row.first.locator("a")
                print(f"[*] Found RCDF link with count: {rcdf_link.inner_text().strip()}. Opening tenders list...")
                rcdf_link.first.click()
                list_page.wait_for_load_state("domcontentloaded")
                list_page.wait_for_timeout(2500)
                table_loaded = True

        tenders_table = list_page.locator("table#table")
        if tenders_table.count() == 0 or tenders_table.first.locator("tr").count() < 2:
            print("[!] Tender table not found or empty.")
            browser.close()
            return []

        all_rows = tenders_table.first.locator("tr")
        total_rows = all_rows.count()
        print(f"[+] Loaded tenders table ({total_rows} total rows).")

        qualifying_tenders = []
        for row_idx in range(1, total_rows):
            cols = all_rows.nth(row_idx).locator("td")
            if cols.count() < 6:
                continue

            s_no = cols.nth(0).inner_text().strip()
            closing_date = cols.nth(2).inner_text().strip()
            title_cell = cols.nth(4)
            title_ref_td = title_cell.inner_text().strip()
            org_chain_td = cols.nth(5).inner_text().strip()

            is_match, _ = is_cattle_feed_tender(title_ref_td, org_chain_td)
            if not is_match:
                continue

            is_retender, ret_reason = has_excluded_keywords(title_ref_td)
            if is_retender:
                print(f"[-] Auto-skipping row {row_idx}: {ret_reason}")
                continue

            is_emp, emp_reason = is_empanelment_title(title_ref_td)
            if is_emp:
                print(f"[-] Auto-skipping row {row_idx}: {emp_reason}")
                continue

            m_tid = re.search(r'\[(\d{4}_[A-Z0-9]+_\d+_\d+)\]', title_ref_td)
            tender_id = m_tid.group(1) if m_tid else ""
            if not tender_id:
                m_tid2 = re.search(r'(\d{4}_[A-Z0-9]+_\d+_\d+)', title_ref_td)
                tender_id = m_tid2.group(1) if m_tid2 else ""

            if tender_id:
                is_ret_id, ret_id_msg = is_retender_id(tender_id)
                if is_ret_id:
                    print(f"[-] Auto-skipping row {row_idx}: {ret_id_msg}")
                    continue

            link_tag = title_cell.locator("a").first
            href = link_tag.get_attribute("href") if link_tag.count() else ""
            if not href:
                continue

            full_href = f"https://eproc.rajasthan.gov.in{href}" if href.startswith('/') else href
            city_folder = detect_plant(title_ref_td, org_chain_td)

            qualifying_tenders.append({
                "row_index": row_idx,
                "s_no": s_no,
                "title_ref": title_ref_td,
                "closing_date": closing_date,
                "city": city_folder,
                "tender_id": tender_id,
                "url": full_href
            })

        print(f"\n[+] Found {len(qualifying_tenders)} qualifying Cattle Feed tenders:")
        for idx, item in enumerate(qualifying_tenders, 1):
            title_disp = item["title_ref"].replace('\n', ' ')
            print(f"  {idx}. [{item['city']:<13}] Tender ID: {item['tender_id']:<24} Closing: {item['closing_date']:<22} {title_disp[:50]}...")

        for i, q in enumerate(qualifying_tenders):
            print("\n" + "=" * 80)
            print(f"[*] Processing ({i+1}/{len(qualifying_tenders)}): [{q['city']}] Tender ID: {q['tender_id']}")
            print("=" * 80)

            tender_tab = context.new_page()
            try:
                tender_tab.goto(q["url"], timeout=60000, wait_until="domcontentloaded")
                tender_tab.wait_for_timeout(2000)
            except Exception as e:
                print(f"[!] Error opening tender URL: {e}")
                tender_tab.close()
                continue

            content_locator = tender_tab.locator("td.page_content")
            detail_text = content_locator.first.inner_text() if content_locator.count() > 0 else tender_tab.locator("body").inner_text()

            detail_id_match = re.search(r'Tender ID\s*[:\s]+([^\s\n\r]+)', detail_text, re.IGNORECASE)
            if detail_id_match:
                extracted_tid = detail_id_match.group(1).strip()
                if extracted_tid:
                    q["tender_id"] = extracted_tid

            if q["tender_id"]:
                is_ret_id, ret_id_msg = is_retender_id(q["tender_id"])
                if is_ret_id:
                    print(f"[-] Auto-skipping on detail page: {ret_id_msg}")
                    tender_tab.close()
                    continue

            has_excluded, exc_reason = has_excluded_keywords(detail_text)
            if has_excluded:
                print(f"[-] Auto-skipping on detail page: {exc_reason}")
                tender_tab.close()
                continue

            city_dir = output_dir / q["city"]
            city_dir.mkdir(parents=True, exist_ok=True)

            saved_boqs = []
            download_successful = False

            # Set up robust download handler for this tender tab
            def on_download(download):
                nonlocal download_successful
                try:
                    s_name = download.suggested_filename
                    print(f"\n[+] Incoming download detected: '{s_name}'")
                    temp_file = city_dir / s_name
                    download.save_as(str(temp_file))
                    print(f"[+] Download successfully saved: {temp_file.name} ({temp_file.stat().st_size:,} bytes)")

                    if zipfile.is_zipfile(temp_file):
                        extracted = _extract_boq_from_zip(temp_file, city_dir)
                        saved_boqs.extend(extracted)
                        download_successful = True
                    elif temp_file.suffix.lower() in ('.xls', '.xlsx'):
                        saved_boqs.append(temp_file.name)
                        download_successful = True
                except Exception as ex:
                    print(f"[!] Error saving intercepted download: {ex}")

            tender_tab.on("download", on_download)

            def find_zip_btn(pg):
                btn = pg.locator("a:has-text('Download as zip file')")
                if btn.count() == 0:
                    btn = pg.locator("a#DirectLink_8")
                if btn.count() == 0:
                    btn = pg.get_by_text("Download as zip file", exact=False)
                return btn

            zip_btn = find_zip_btn(tender_tab)

            if zip_btn.count() > 0:
                print(f"[*] Clicking 'Download as zip file' for {q['city']}...")
                zip_btn.first.scroll_into_view_if_needed()
                zip_btn.first.click()

                # Wait for either CAPTCHA form to appear OR direct download to start
                for _ in range(90):
                    if download_successful or len(saved_boqs) > 0:
                        break
                    c_form = tender_tab.locator("form#frmCaptcha, input#captchaText")
                    if c_form.count() > 0 and c_form.first.is_visible():
                        break
                    tender_tab.wait_for_timeout(500)

                max_attempts = 3
                for attempt in range(max_attempts):
                    if download_successful or len(saved_boqs) > 0:
                        break

                    captcha_form = tender_tab.locator("form#frmCaptcha, input#captchaText")
                    if captcha_form.count() > 0 and captcha_form.first.is_visible():
                        print(f"[*] Prompting CAPTCHA dialog for {q['city']} (Attempt {attempt+1}/{max_attempts})...")
                        img_tag = tender_tab.locator("img#captchaImage")
                        img_src = img_tag.get_attribute("src") if img_tag.count() else ""

                        user_code = prompt_user_captcha_gui(q["city"], q["tender_id"], img_src, i+1, len(qualifying_tenders))
                        if not user_code:
                            print("[!] Waiting for user input in browser or GUI...")
                            for _ in range(30):
                                if download_successful or len(saved_boqs) > 0:
                                    break
                                tender_tab.wait_for_timeout(1000)
                            break

                        tender_tab.locator("input#captchaText").fill(user_code)
                        print(f"[*] Submitted code: '{user_code}'. Monitoring portal response & download...")
                        tender_tab.locator("input#Submit").click()

                        # Wait for download, or detect redirect back to tender page where Download button needs clicking again
                        clicked_post_captcha = False
                        t_start = time.time()
                        while time.time() - t_start < 90:
                            if download_successful or len(saved_boqs) > 0:
                                break

                            elapsed = time.time() - t_start
                            if elapsed >= 2.0 and not clicked_post_captcha:
                                try:
                                    post_captcha_form = tender_tab.locator("form#frmCaptcha, input#captchaText")
                                    re_zip_btn = find_zip_btn(tender_tab)
                                    if post_captcha_form.count() == 0 and re_zip_btn.count() > 0 and re_zip_btn.first.is_visible():
                                        print(f"[*] CAPTCHA unlocked session -> scrolling & clicking 'Download as zip file' for {q['city']}...")
                                        re_zip_btn.first.scroll_into_view_if_needed()
                                        tender_tab.wait_for_timeout(500)
                                        re_zip_btn.first.click()
                                        clicked_post_captcha = True
                                        t_start = time.time()  # Give full 90s for zip packaging after clicking download
                                except Exception:
                                    pass

                            if elapsed >= 2.0 and tender_tab.locator("form#frmCaptcha").count() > 0:
                                try:
                                    body_text = tender_tab.locator("body").inner_text()
                                    if "Invalid Captcha" in body_text:
                                        print("[!] Portal reported: 'Invalid Captcha! Please Enter Correct Captcha.'")
                                        break
                                except Exception:
                                    pass

                            tender_tab.wait_for_timeout(500)

                        if download_successful or len(saved_boqs) > 0:
                            break
                        else:
                            print("[!] Download not received. Retrying CAPTCHA if attempts remain...")
                            tender_tab.wait_for_timeout(1500)
                    else:
                        # No CAPTCHA form (session already unlocked); wait up to 90s for server packaging & download
                        t_start = time.time()
                        while time.time() - t_start < 90:
                            if download_successful or len(saved_boqs) > 0:
                                break
                            tender_tab.wait_for_timeout(500)
                        break

            # Fallback scan: check if any zip or BOQ was placed in city_dir or output_dir
            for zf in city_dir.glob("*.zip"):
                ext = _extract_boq_from_zip(zf, city_dir)
                for ef in ext:
                    if ef not in saved_boqs:
                        saved_boqs.append(ef)

            for xf in city_dir.glob("BOQ_*.xls*"):
                if xf.name not in saved_boqs:
                    saved_boqs.append(xf.name)

            for bf in saved_boqs:
                f_path = city_dir / bf
                downloaded_records.append({
                    "city": q["city"],
                    "tender_id": q["tender_id"] or "N/A",
                    "closing_date": q["closing_date"],
                    "boq_file": bf,
                    "file_path": str(f_path),
                    "file_size": f_path.stat().st_size if f_path.exists() else 0
                })

            tender_tab.close()

        browser.close()

    # Clean up any orphan GUID files created by Chromium download buffer
    for item in output_dir.glob("*"):
        if item.is_file() and re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', item.name):
            try:
                item.unlink()
            except Exception:
                pass

    _print_summary(downloaded_records, output_dir)
    return downloaded_records

def _extract_boq_from_zip(zip_path: Path, dest_dir: Path) -> List[str]:
    saved_files = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.namelist():
                filename = os.path.basename(member)
                if not filename:
                    continue
                ext = os.path.splitext(filename)[1].lower()
                if ext in ('.xls', '.xlsx'):
                    target_file = dest_dir / filename
                    with zf.open(member) as src, open(target_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if target_file.exists() and target_file.stat().st_size > 0:
                        print(f"    [+] Extracted BOQ: {target_file.name} ({target_file.stat().st_size:,} bytes)")
                        saved_files.append(target_file.name)
    except Exception as e:
        print(f"[!] Failed to extract zip {zip_path}: {e}")
    return saved_files

def _print_summary(records: List[Dict], output_dir: Path):
    print("\n" + "=" * 96)
    print(" RCDF BOQ DOWNLOAD & EXTRACTION SUMMARY")
    print("=" * 96)
    print(f"Output Base Directory: {output_dir.resolve()}\n")
    if not records:
        print("No BOQ files were downloaded. Please check portal logs above.")
        print("=" * 96)
        return

    hdr_city = "City Folder"
    hdr_id = "Tender ID"
    hdr_close = "Closing Date"
    hdr_boq = "Saved BOQ File"
    hdr_size = "Size (KB)"

    print(f"{hdr_city:<15} | {hdr_id:<25} | {hdr_close:<22} | {hdr_boq:<24} | {hdr_size}")
    print("-" * 96)
    for r in records:
        size_kb = f"{r.get('file_size', 0) / 1024:.1f} KB"
        print(f"{r['city']:<15} | {r['tender_id']:<25} | {r['closing_date']:<22} | {r['boq_file']:<24} | {size_kb}")
    print("-" * 96)
    print(f"Total BOQ files organized: {len(records)}")
    print(f"Full Local Path: {output_dir.resolve()}")
    print("=" * 96)

def main():
    parser = argparse.ArgumentParser(description="RCDF eProc BOQ Downloader")
    parser.add_argument("--url", default=DEFAULT_RCDF_URL, help="Organisation URL")
    parser.add_argument("--output", default=None, help="Output folder")
    parser.add_argument("--headless", action="store_true", help="Headless browser")
    args = parser.parse_args()

    run_boq_downloader(
        portal_url=args.url,
        output_base=args.output,
        headless=args.headless
    )

if __name__ == "__main__":
    main()
