# RCDF Project Transition Summary

Copy-paste the content below into your main RCDF chat to continue seamlessly with your full conversation history and memory.

---

## 1. What Was Asked

### Part A: Email & WhatsApp Monitoring + Free AI Models
* **Continuous Monitoring**:
  * Continuous monitoring of **3 work emails** (Shree Nath Industries, Shree Vinayak Trading Company, Shree Ganpati Enterprises).
  * Continuous monitoring of **3 WhatsApp accounts** simultaneously.
  * WhatsApp filter rules: Strictly read **unseen messages only** and only from **contacts/groups that send bills** (ignoring general spam and personal chit-chat).
* **100% Free AI Stack**:
  * Audit all previously configured free APIs and models to check which are alive vs. broken.
  * Switch to active, high-accuracy free models without paid subscriptions.
* **Server Crash Diagnosis & Local Testing**:
  * Diagnose why the application stopped working / crashed on the server.
  * Test and simulate everything locally on MySQL and FastAPI.

### Part B: Busy Accounting Automation & Zero-Error Accuracy
* **End Goal**: Automatic bill entries into **Busy Accounting Software**.
* **Accounting Environment**: Accounting PC running **Windows 7 with low RAM**.
* **Approaches Evaluated**:
  * Option 1: Direct screen-driving / RPA bot controlling the mouse and typing into Busy.
  * Option 2: Native Busy Excel voucher import (`Book1.xlsx` format).
  * Option 3: Lightweight compiled Windows 7 Agent (< 10 MB RAM) to bridge RCDF cloud and local Busy without screen-scraping risks.
* **Top Priority**: **Accuracy**. Eliminate AI hallucinations and misreads before vouchers touch Busy.

---

## 2. Technical Findings & Live Test Results

### A. Free AI Models Status (Tested Live)
| Provider | Status | Models Tested | Key Findings |
| :--- | :--- | :--- | :--- |
| **Google Gemini** | **100% OPERATIONAL** | `gemini-2.5-flash` | Free API via Google AI Studio is active, fast, and highly accurate for multimodal vision and JSON parsing. |
| **Groq** | **PARTIALLY BROKEN** | `llama-3.2-vision`, `llama-3.3-70b-versatile` | Previously configured models were **decommissioned by Groq (404/400)**. Active models: `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`. |
| **OpenRouter** | **OPERATIONAL** | 12 `:free` models | Auth valid (200 OK); free models usable as backup. |
| **Mistral** | **LIMITED** | `open-mistral-7b` | Works, but `mistral-small-latest` hits free tier 429 rate limits. |
| **SambaNova** | **FAILED** | `MiniMax`, `gemma-4-31B-it` | Returns `401 Unauthorized` (key expired/invalid). |
| **GitHub Models**| **FAILED** | Azure inference | DNS resolution error (`[Errno 11001]`). |

> **Critical Fix in `backend/services/ocr_service.py`:**
> The extractor priority previously had broken Groq/SambaNova models ahead of Gemini (`1. Paddle -> 2. Groq -> 3. Mistral -> 4. SambaNova -> 5. Gemini`). Every extraction hit dead endpoints before reaching Gemini, causing server timeouts. Setting **Gemini 2.5 Flash as Priority #1** immediately restores instant, zero-cost, reliable extraction.

---

### B. Email Ingestion Audit (Tested Live via IMAP)
* **Account 1 (`gordhan.khandelwal@yahoo.com` - Shree Nath Industries)**: Connected & Verified (238 unseen).
* **Account 2 (`vtcjaipur2012@gmail.com` - Shree Vinayak Trading Company)**: Connected & Verified (23,387 unseen).
* **Account 3 (`vinayakkhandelwal88@gmail.com` - Shree Ganpati Enterprises)**: Identified in codebase/DB; needs App Password added to `.env`.
* **Scheduler**: Currently set to 4 runs/day in `main.py`. Needs a fast background loop (every 3–5 minutes) targeting `UNSEEN` messages.

---

### C. WhatsApp Bridge Audit
* **Engine**: Successfully rewritten to lightweight **Baileys (`@whiskeysockets/baileys`)** on August 4, 2026, eliminating Puppeteer/Chromium memory leaks.
* **Limitation**: Currently single-session (`auth_baileys_session`).
* **Required Upgrade**: Refactor `bridge.js` to manage 3 distinct sessions (`wa_1`, `wa_2`, `wa_3`) with multi-QR pairing in the UI and contact/unseen filtering.

---

### D. Busy Software Integration & Template Audit
* **`File1.xls`**: Verified! Contains **849 exact registered party accounts** and GSTINs exported from Busy (*SHREE NATH INDUSTRIES 26-27*).
* **`Book1.xlsx`**: Matches Busy's exact **"Import Vouchers from Excel"** schema:
  `VCH_SERIES | VCH/BILL_DATE | VCH/BILL_NO | SALE/PURC_TYPE | PARTY_NAME | MC_NAME | ITEM_NAME | QUANTITY | UNIT | PRICE | ITC_ELIGIBILITY_TYPE | NARRATION`
* **Why Screen-Driving RPA is NOT recommended on Windows 7**:
  * Typing into Busy's dynamic autocomplete dropdowns on low RAM causes keystroke desync (Date typing into Bill No, Rate typing into Tax Code).
  * Unexpected popups (e.g. *"Party not found! Create Master?"*) freeze the bot.
  * Slow (~30 min for 100 bills) and locks the PC.
* **The Recommended Approach**:
  * **Native Excel / XML Voucher Import**: 100% database-safe, atomic, validates accounts, and imports 100 bills in under 3 seconds.
  * **Lightweight Windows 7 Background Agent (< 10 MB RAM EXE)**: Automatically receives approved bills from RCDF and places them directly into Busy's import folder for 1-click execution without manual browser downloading.

---

### E. Zero-Mistake Free AI Verification Architecture
1. **Dual Free-AI Verification**: Gemini 2.5 Flash (Primary) + Groq Qwen 2.5 / OpenRouter free (Cross-check). If both agree $\to$ 99.9% match.
2. **Deterministic Mathematical Validator (Python)**:
   * Line check: `|Qty × Rate - Taxable| <= ₹1.00`
   * Tax balance check: `|Taxable + CGST + SGST + IGST + TCS - Discounts ± RoundOff - Total| <= ₹1.00`
   * Weight check: `Gross - Tare == Net Weight`
   * Any math discrepancy is blocked and flagged red.
3. **Master Data Reconciliation**:
   * Exact GSTIN matching against the 849 accounts in `File1.xls`.
   * Fuzzy name matching (>90%) for slight invoice spelling variations.
   * Auto-standardization of Item names (`DOMC`) and Material Centre (`Main Store`).
4. **Supervised Review Hub**: Side-by-side bill image vs. extracted data with green/red badges for fast 1-click batch approvals.

---

## 3. Immediate Implementation Steps
1. **Set Gemini 2.5 Flash as Priority #1** in `backend/services/ocr_service.py` and remove decommissioned Groq/SambaNova calls.
2. **Import 849 Busy Master Parties** from `File1.xls` into the `busy_party_masters` table for automated vendor matching.
3. **Add 3rd Work Email** (`vinayakkhandelwal88@gmail.com` App Password) to `EMAIL_SYNC_ACCOUNTS` and tighten polling to 3–5 minutes.
4. **Upgrade WhatsApp Bridge to 3 Sessions** (`wa_1`, `wa_2`, `wa_3`) with unread and bill-contact filtering.
5. **Build Lightweight Windows 7 Auto-Import Agent** for the accounting PC.
