import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    r = conn.execute(text("SELECT COUNT(1) AS cnt FROM pending_ingests"))
    row = r.mappings().first()
    print("pending_ingests_count:", int(row.get("cnt") or 0))
