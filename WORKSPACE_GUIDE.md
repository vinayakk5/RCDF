# Firm → RM workspace: what changed and how to use it

Branch: `claude/project-thread-9bp0xr` (built on `claude/project-thread-5n5cpu`).

## Get it running on the laptop

```
git fetch origin claude/project-thread-9bp0xr
git checkout claude/project-thread-9bp0xr
cd backend
python -m migrations status      # 0005 "RM status and tender PO links" shows as PENDING
python -m unittest discover -s tests
uvicorn main:app --host 127.0.0.1 --port 8000
```

Migration 0005 runs by itself at startup. It only adds two columns to `main_tenders`
(`status`, `closed_at`) and links old sub-tenders to their PO. Nothing is deleted.

Errors are now also written to `backend/logs/app.log` (rotated at 5 MB, 5 files).
Set `LOG_TO_FILE=false` to turn that off.

## How the screens are organised

1. **Firm** (bar at the top): All firms, Ganpati, Nath, Vinayak.
2. **Tenders (RM)**: the RM list for that firm. Filter by text, Active / Closed / Archived, and
   supply dates. Each row shows plants, quantity, progress, PO value, and how many documents
   or bills are waiting to be checked. Below the list, "Seen in email, not set up yet" shows
   RM numbers that arrived in documents but have no approved PO yet (for example RM-842, RM-845).
3. **One RM**: numbers at the top, then tabs: Overview (sub-tenders and broker deals),
   Purchase orders (lines, our value, open the PO file, sub-tender preview), To check
   (documents in the Inbox that mention this RM), Bills, Dispatch, Unloading, Rejections,
   Sales bills, Payments. "Open full screen" on each tab goes to the older page, already
   filtered to this RM, for approving and editing.
4. **Search**: Ctrl+K (or `/`, or the search box). Finds RMs, sub-tenders, PO numbers, bill
   numbers, trucks (spaces and dashes ignored), unloading WS numbers, purchase and sales bill
   numbers, brokers and Inbox documents. Tick "All firms" to look across firms.

Close RM / Archive / Reopen are on the RM page. Closed RMs leave the Active list; archived ones
are hidden everywhere except the Archived filter. Both can be reopened; nothing is deleted.

## Fixes in this branch

- **PO amount**: lists show only the value of lines approved to our firm, as ₹1.56 Cr with the
  full figure next to it. The total printed on the PO is shown separately when it differs.
- **Sub-tender preview**: tender names now come from the RM (RM-844 Domc Kaladera), not from
  the PO number (which produced "RM-21064 ...").
- **Old sub-tenders** are linked back to their PO (migration 0005).
- **Time-extension orders** that the readers filed as "purchase order" no longer try to make a
  PO. They show as "Time extension" under the RM's To check tab with an **Apply extension**
  button that moves the supply end date (it never shortens a date).
- **Email**: once a mailbox has a checkpoint, new mail is read even if someone already opened
  it on the phone. Before, the 3-minute sync only took *unread* mail, so any PO opened first
  was skipped for good. (`EMAIL_SYNC_INCREMENTAL_UNREAD_ONLY=true` brings the old behaviour back.)
- Typing in the search boxes of the older pages now waits 250 ms before asking the server,
  instead of one request per key.

## Things only you can do

- **Third mailbox (Shree Ganpati)**: add it to `EMAIL_SYNC_ACCOUNTS` in `backend/.env` with its
  Gmail app password. It has never been read so far.
- **Re-scan for missed POs** (one time, after pulling): Inbox page > email sync with
  "unread only" off and 60 days back, or
  `POST /api/ingest/email/sync?since_days=60&unread_only=false` while logged in as admin.
  Duplicates are skipped automatically.
- The Groq reader model `llama-3.3-70b-versatile` has been retired by Groq and fails on every
  document; the other readers cover for it.
