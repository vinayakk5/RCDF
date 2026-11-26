# RCDF Supply — handoff (read this first)

Written 26 Nov 2026 so work can continue in a plain Claude Code chat on the laptop.
Repo: `C:\Users\user\Desktop\freelancer\business\rcdf` (GitHub `vinayakk5/RCDF`).
**Current branch: `claude/project-thread-9bp0xr`** (this is what runs on the laptop).

## 1. The business in one page

Three firms supply cattle-feed raw material (Maize, DOMC, etc.) to RCDF plants
(Ajmer, Pali, Jodhpur, Kaladera, Gulabpura, Nadbai, Bikaner ...):

| id | Firm | Mailbox |
|---|---|---|
| 1 | Shree Ganpati Enterprises | Gmail (not connected yet, see open items) |
| 2 | Shree Nath Industries | Yahoo |
| 3 | Shree Vinayak Trading Company | vtcjaipur Gmail |

Flow of one tender:
1. **Tender notice (NIT)** for an **RM number** (e.g. RM-844). Tenders overlap in time.
2. **Purchase orders (POs)**: one per plant from RCDF. Each PO lists every item of that plant with
   the party approved for it; only lines approved to *our* firm count. Many POs per RM, and the same
   RM can be won by more than one of our firms (separate RM record per firm).
3. In the app: **Firm → RM (`main_tenders`) → sub-tenders (`tenders`, one per plant + material)**.
   Sub-tenders are created only from approved POs. Sale rate per quintal comes from the PO line.
4. **Deals** with brokers (qty, our purchase rate per quintal).
5. Broker **purchase bills** arrive (email/WhatsApp/photo) → Inbox (`pending_ingests`) → reviewed →
   `bills` → matched to firm/RM/deal by bill date and plant.
6. **Dispatch** (truck to plant) → **plant unloading register / weighbridge** → **rejection letters**.
   `plant_receipts` hold accepted / rejected qty per truck.
7. **Sales bill** to the plant = accepted qty × PO rate (one or many trucks, one firm, one plant).
8. **Payment to broker** = accepted qty × deal rate, minus what was paid.
9. Everything exports to **Busy** accounting (Excel voucher import, Book1 layout). A small Windows 7
   agent can pull purchase-bill exports with `MACHINE_API_KEY`.

Units: all quantities are **quintals** even where a column is named `*_mt` (legacy names).

## 2. Code map

- `backend/main.py` — FastAPI app, ~12k lines, all routes. Serves `frontend/` at `/` and `/static`.
- `backend/models.py` — SQLAlchemy models (MySQL 8).
- `backend/migrations/` — versioned migrations, run automatically at startup.
  `python -m migrations status|upgrade`. 0001–0005 applied on the laptop.
- `backend/services/` — `email_sync_service.py` (IMAP), `ocr_service.py` (document readers: Gemini
  first, then others), `document_verifier.py`, `bill_verifier.py`, `sales_billing.py`, `busy_export.py`,
  `auth.py` (login + roles: admin, accountant, operator, viewer), `workspace.py` (RM list / RM page /
  search, new).
- `frontend/index.html` — the single-page app (~8.7k lines). `frontend/workspace.js` + `.css` add the
  firm → RM layer on top (new).
- `backend/tests/` — 115 unit tests on SQLite: `cd backend; python -m unittest discover -s tests`.

## 3. Branch history

| Branch | What it holds |
|---|---|
| `master` | initial commit only |
| `claude/project-thread-r5kw1r` | phase 2: bill assignment by bill date, rejection letters |
| `claude/project-thread-z3pb8a` | + phone-friendly frontend with camera upload |
| `claude/project-thread-5n5cpu` | + phase 3/4: sales bills, payments due, Busy exports, dual readers, auto-approval (shadow), login, migrations. Guide: `PHASE3_TO_4_GUIDE.md` |
| **`claude/project-thread-9bp0xr`** | + firm → RM workspace, Ctrl+K search, RM close/archive, PO value fix, extension orders, email fix, file log. Guide: `WORKSPACE_GUIDE.md` |

Each branch is built on the one above it. Nothing has been merged to `master`.

## 4. Running it

```
cd C:\Users\user\Desktop\freelancer\business\rcdf\backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```
Open http://localhost:8000 (port **8000**, not 8004). Settings are in `backend\.env`.
Errors go to `backend\logs\app.log`. MySQL runs locally on 3306.

Do not touch `start_tunnel.py` / `server.py` (port 8080, cloudflared tunnel): they belong to a
different project in `C:\Users\user\Desktop\nannu\website`.

## 5. What was done on 26 Nov 2026

- Explained the screen: only 2 RMs existed because only 5 PO emails had ever been approved
  (4 × RM-836 in July, 1 × RM-844 Kaladera). Nothing after the PO stage existed: bills, dispatch,
  receipts, unloading, sales bills and payments were all 0 rows. The documents for them sit in the Inbox.
- "15 crore" was really ₹1,56,34,550 = ₹1.56 Cr (5,000 qtl × ₹3,126.91).
- Built the firm → RM workspace (see `WORKSPACE_GUIDE.md`).
- Fixed: PO value counts only our lines; sub-tender preview named from the RM, not the PO number;
  old sub-tenders linked to their POs (all six now linked); time-extension orders filed as POs no longer
  touch sub-tenders and can be applied with "Apply extension"; email sync now reads new mail even if
  it was already opened on a phone (this is the likely reason POs went missing); 250 ms debounce on
  page searches; rotating file log.
- **DB backup before the update:** `backend\backups\rcdf_before_0005_20261126_134306.sql` (1.09 MB).
- Migration 0005 applied on the laptop. Server restarted on the new branch (port 8000).
- **RM-836 closed** (main_tenders status = closed, can be reopened from the RM page). Its five
  sub-tenders (ids 1–5) were also set to status `complete`.
- Started a one-time 60-day email re-scan (all senders, read and unread, checkpoint not moved).
  Matched 452 Yahoo + 208 Gmail messages; cap was 400 per account, so the 52 oldest Yahoo messages
  (days ~55–60) were not covered. Results: see section 7.

## 6. Open items

1. **Shree Ganpati mailbox**: add it to `EMAIL_SYNC_ACCOUNTS` in `backend\.env` with a Gmail app
   password (only commented out today). Never read so far. Then run a 60-day re-scan for it.
2. **Original POs for RM-842 (Jodhpur) and RM-843 (Pali/Ajmer)**: only their time-extension orders
   arrived. Find the original POs (maybe in the Ganpati mailbox or the re-scan) and approve them.
3. **Inbox backlog** (~70+ pending documents): 30 unloading sheets, 24 rejection letters, ~15 purchase
   bills, 11 tender notices, 6 "POs" that are really extensions (ingests 50, 53, 54, 55, 66) and one
   empty PO (17). Until reviewed, bills/dispatch/receipts stay empty.
4. **Old server DB dump** never arrived, so history before July is missing.
5. **Busy payment voucher** Excel layout (`ACCOUNT_DR`, `ACCOUNT_CR`, ...) must be checked against one
   manual payment import in Busy before relying on it.
6. **`MACHINE_API_KEY`** in `.env` (and the same value in the Busy agent's `busy_agent_config.json`).
7. **Groq reader** model `llama-3.3-70b-versatile` is retired (404 on every document). Others cover it;
   replace or remove it in `ocr_service.py`.
8. Auto-approval is in `shadow` mode; switch to `live` only when its report says it is ready.
9. Old RM-836 Kaladera etc. PO files from July are missing on disk (`backend/uploads/pending_ingests`).

## 7. Re-scan results

(filled in when the 60-day re-scan finished; if empty, check the Inbox for documents created on
26 Nov 2026 with sync reason `rescan_60d`.)

## 8. Gotchas

- The laptop's Claude Code auto mode refuses to stop/start servers unless the request is typed by the
  user in that same chat. Expect to approve restarts yourself.
- Old server + new frontend files = broken screens: the server reads HTML/JS from disk on every request,
  so after `git checkout` always restart uvicorn.
- `pending_ingests.file_path` mixes `/` and `\` separators; paths are relative to `backend/uploads/`.
- RM numbers are read loosely: "RM844ANIT", "NITRM845", "RM 844 SHEET" all map to RM-844 / RM-845.
- An RM is per firm: the same RM code under two firms is two `main_tenders` rows.
- A PO's printed total includes other parties' lines; use `our_amount` / line items for our value.
- `main_tenders.status` (active/closed/archived) is the real state; `is_active` is kept false only for
  archived, so the old context selector still works.
- Auth is on (`AUTH_ENABLED=true`): API calls need a login cookie or `Authorization: Bearer`.
- Tests never touch MySQL; they build SQLite in memory.
