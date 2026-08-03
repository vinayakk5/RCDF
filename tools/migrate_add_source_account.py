import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from database import engine
from sqlalchemy import text

sql = """
ALTER TABLE pending_ingests
ADD COLUMN source_account VARCHAR(200);
"""

check_sql = text(
    "SELECT COUNT(1) as cnt FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'pending_ingests' AND column_name = 'source_account'"
)

with engine.connect() as conn:
    r = conn.execute(check_sql).mappings().first()
    exists = bool(r and int(r.get("cnt") or 0) > 0)
    if exists:
        print("SKIP: pending_ingests.source_account already exists")
    else:
        conn.execute(text(sql))
        conn.commit()
        print("OK: added pending_ingests.source_account")
