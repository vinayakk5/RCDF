# Phases 3 to 4: what changed and how to test

Branch: `claude/project-thread-5n5cpu` (built on `claude/project-thread-z3pb8a`).

## Get it running

```
git fetch origin claude/project-thread-5n5cpu
git checkout claude/project-thread-5n5cpu
cd backend
pip install -r requirements.txt
python -m migrations status      # shows 0001..0004 as PENDING on your DB
python -m unittest discover -s tests    # 102 tests, SQLite only, never touches MySQL
uvicorn main:app --port 8000
```

Migrations also run by themselves when the server starts (set `AUTO_MIGRATE=false` to stop that).
Take a MySQL backup before the first start on the server DB.

## New settings (.env)

| Setting | Default | What it does |
|---|---|---|
| `AUTH_ENABLED` | `true` | Login required. `false` = old behaviour, no login. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | empty | Creates the first admin at startup if there are no users. Otherwise the login screen asks you to create one. |
| `AUTH_SESSION_DAYS` | `7` | How long a login lasts. |
| `MACHINE_API_KEY` | empty | Key for the Busy agent (`X-API-Key`). Put the same value in the agent's `busy_agent_config.json` as `api_key` (the admin download of the agent package fills it in). |
| `AUTO_APPROVE_MODE` | `shadow` | `shadow` = only record decisions, `live` = approve bills that pass every check, `off`. |
| `AUTO_APPROVE_MAX_RATE_OVER_DEAL` | `0.02` | Bill rate may be at most 2% above the deal rate. |
| `AUTO_APPROVE_MAX_BILL_AGE_DAYS` | `45` | Older bills always go to a person. |
| `BUSY_PAYMENT_BANK_ACCOUNT` (or `_<company_id>`) | `Bank` | Busy account the payment is made from. |

The WhatsApp bridge on the same machine (127.0.0.1) needs no key.

## Try each feature

1. **Login**: open the app; first time it asks you to create the admin. Admin > Users adds people
   with a role: admin, accountant (bills, payments, sales bills, Busy), operator (upload/review
   documents and plant unloading, no payments, deletes or exports), viewer (read only).
2. **Sales bills**: Sales Bills > Make sales bill lists every plant-unloaded truck not yet billed
   (accepted qty, rate from the PO). Tick 1 or 10 trucks of one firm and one plant, Create.
   A truck can never be billed twice (also enforced by a unique index). Cancel frees its trucks.
   If a rejection arrives after billing, the bill shows "plant qty changed".
   If a tender has no rate, set it in Tenders > Edit ("Our sale rate to plant").
3. **Busy export**: tick sales bills > Export selected to Busy (Book1 layout, one row per truck,
   same bill no.). Payments > Payment vouchers > Export selected to Busy. The agent can pull
   `GET /api/export/sales-bills/busy-xlsx` and `/api/export/payments/busy-xlsx` with the key.
4. **Payments**: Payments > Due to pay lists only bills with a plant result:
   accepted qty x deal rate, minus what is paid; overpaid bills show the amount to recover.
5. **Unloading register / weighbridge / tender notice / PO**: upload as before. Each photo or PDF
   is now read by two free readers from different providers. Rows the readers disagree on (or that
   fail a check: gross - tare = net, bag weight, net <= received, running total) come in as
   flagged with the reason in notes. Excel sheets are parsed locally as before.
6. **Auto-approval**: Intelligence > Auto-approval shows what it would have done with each pending
   purchase bill and whether you agreed. It runs after every email sync, or with "Check pending
   bills now". Switch to `live` only when the page says it is ready (50+ reviewed, zero wrong).

## Not done yet

- The Windows 7 Busy agent still only pulls purchase bills; sales bills and payments are exported
  from the web page (or the agent can be pointed at the new URLs).
- The payment voucher Excel layout (`ACCOUNT_DR`, `ACCOUNT_CR`, ...) should be checked against
  one manual payment import in Busy before relying on it.
