#!/usr/bin/env bash
# ============================================================
# RCDF Supply — One-command local setup
# Usage: bash setup.sh
# ============================================================
set -e

echo "=== RCDF Supply Setup ==="

# 1. Check Python
python3 --version || { echo "Python 3.9+ required"; exit 1; }

# 2. Create virtual env
cd backend
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
echo "Installing Python packages (this takes a few minutes on first run)..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Copy .env
cd ..
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo ">>> .env file created. EDIT IT before running:"
  echo "    - DB_PASSWORD   (your MySQL root password)"
  echo "    - GEMINI_API_KEY  (free from aistudio.google.com)"
  echo "    - TELEGRAM_TOKEN  (from @BotFather on Telegram — optional)"
  echo ""
fi

# 5. Create MySQL database and schema
echo "Setting up MySQL database..."
read -p "MySQL root password: " -s MYSQL_PASS
echo ""
mysql -u root -p"$MYSQL_PASS" < database/schema.sql && echo "Database schema created."

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start the server:"
echo "  cd backend"
echo "  source venv/bin/activate"
echo "  uvicorn main:app --reload --port 8000"
echo ""
echo "Then open: http://localhost:8000"
echo ""
