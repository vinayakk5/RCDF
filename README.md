# RCDF Supply — Operations Platform

Full-stack operations system for RCDF cattle feed raw material supply.
Covers all 9 modules: Tenders, Deals, Bill OCR, Dispatch, Purchase Bills,
Sales Bills, Payments, Market Prices, Reports.

## Tech stack

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy
- **Database**: MySQL 8.0
- **OCR**: PaddleOCR (local, free) + Gemini 1.5 Flash (free API)
- **Telegram bot**: python-telegram-bot (free)
- **Frontend**: Vanilla HTML/CSS/JS SPA (no build step, no Node needed)

## Project structure

```
rcdf/
├── backend/
│   ├── main.py              ← FastAPI app + all API routes
│   ├── database.py          ← MySQL connection + settings
│   ├── models.py            ← All SQLAlchemy ORM models
│   ├── requirements.txt
│   └── services/
│       ├── ocr_service.py   ← PaddleOCR + Gemini router
│       ├── telegram_service.py ← Telegram webhook handler
│       └── busy_export.py   ← Busy accounting CSV generator
├── frontend/
│   └── index.html           ← Complete SPA (all modules in one file)
├── database/
│   └── schema.sql           ← Full MySQL schema with sample data
├── .env.example
├── setup.sh
└── README.md
```

## Quick start

### Step 1 — Prerequisites

- Python 3.9+
- MySQL 8.0 running locally
- Git

### Step 2 — Clone and setup

```bash
git clone <your-repo>
cd rcdf
bash setup.sh
```

Or manually:

```bash
# Setup database
mysql -u root -p < database/schema.sql

# Setup Python
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cd ..
cp .env.example .env
# Edit .env with your MySQL password and API keys
```

### Step 3 — Configure .env

Open `.env` and set at minimum:

```
DB_PASSWORD=your_mysql_password
GEMINI_API_KEY=your_free_gemini_key    # aistudio.google.com — no card needed
```

Optional (needed for Telegram bot):
```
TELEGRAM_TOKEN=from_botfather
WEBHOOK_URL=https://your-ngrok-url.ngrok.io
```

### Step 4 — Start the server

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

## API documentation

FastAPI auto-generates interactive docs at:
- http://localhost:8000/docs  (Swagger UI)
- http://localhost:8000/redoc (ReDoc)

## Module guide

### Dashboard
Shows live summary: tender MT, dispatched/accepted, penalty risks, bill counts, financial overview.

### Tenders
Create and track sproxx cycle tenders per plant + material. Each tender shows all broker deals, progress bars, week-1 deadline status.

### Deal Tracker
All broker deals across all tenders. Track how much each broker has dispatched vs accepted.

### Bill Review
The main daily workflow:
1. Bills arrive via Telegram (auto-processed) or web upload
2. OCR extracts: vendor, vehicle, qty, rate, total, material, date
3. You review extracted fields, correct any errors
4. Link bill to a broker deal
5. Approve → purchase bill auto-generated

### Dispatch Tracking
Add plant receipt records (accepted/rejected MT per vehicle) manually or auto-parsed from rejection emails.

### Purchase Bills
Auto-generated when a bill is approved. Shows all pending broker payments. One-click "Pay" to record payment and generate Busy voucher.

### Sales Bills
Bills sent to RCDF plants for payment. Export to Busy CSV for accounting.

### Payments
All broker payment vouchers. Export to Busy for entry.

### Market Prices
Track mandi prices for Maize, Dorb, Doms, Rice DDGS. Useful for tender bid pricing.

### Reports
- Penalty risk report: which tenders are at risk of week-1 breach
- Broker performance: fulfillment % and rejection rates

## Telegram bot setup

1. Message @BotFather on Telegram → /newbot → get token
2. Add token to `.env` as `TELEGRAM_TOKEN`
3. For local testing, install ngrok: https://ngrok.com
4. Run: `ngrok http 8000`
5. Copy the HTTPS URL to `.env` as `WEBHOOK_URL=https://xxxx.ngrok.io`
6. Register webhook: `curl http://localhost:8000/api/telegram/set-webhook`
7. Add brokers in the Brokers module with their Telegram chat IDs

To get a broker's Telegram chat ID: have them send any message to your bot,
check your server logs — the chat_id is printed there.

## Busy accounting export

Purchase bills, sales bills, and payment vouchers can all be exported as
CSV files compatible with Busy's voucher import format.

In each module, select the rows to export → click "Export to Busy" →
download the CSV → import in Busy via: Transactions → Import Vouchers.

## PaddleOCR note

First run downloads ~500MB of models. After that it's cached locally.
If you don't want PaddleOCR, remove it from requirements.txt —
the system will fall back to Gemini for all bills.

## Deployment (later)

For production, deploy to any VPS (DigitalOcean, AWS, etc.):

```bash
# Install MySQL, Python, nginx
# Use gunicorn instead of uvicorn:
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Point nginx to port 8000
# Get SSL via certbot for Telegram webhook HTTPS requirement
```
