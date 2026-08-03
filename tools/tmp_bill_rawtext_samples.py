import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from database import SessionLocal
from models import Bill
from sqlalchemy import select

db = SessionLocal()
ids = [13, 14]
rows = db.execute(select(Bill).where(Bill.id.in_(ids))).scalars().all()
out = []
for b in rows:
    raw = str(b.ocr_raw_text or "")
    out.append({
        "id": b.id,
        "broker_name": b.broker_name,
        "bill_number": b.bill_number,
        "bill_date": str(b.bill_date) if b.bill_date else None,
        "plant_name": b.plant_name,
        "ocr_raw_text_head": raw[:1400],
    })
print(json.dumps(out, indent=2, ensure_ascii=False))
db.close()
