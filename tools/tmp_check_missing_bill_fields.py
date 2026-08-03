import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from database import SessionLocal
from models import Bill
from sqlalchemy import select, desc

db = SessionLocal()
rows = db.execute(select(Bill).order_by(desc(Bill.id)).limit(80)).scalars().all()
out = []
for b in rows:
    missing = []
    if b.bill_date is None:
        missing.append("bill_date")
    if (b.plant_id is None) and (not str(b.plant_name or "").strip()):
        missing.append("plant")
    if missing:
        out.append({
            "id": b.id,
            "broker_name": b.broker_name,
            "bill_number": b.bill_number,
            "bill_date": str(b.bill_date) if b.bill_date else None,
            "plant_name": b.plant_name,
            "image_path": b.image_path,
            "missing": missing,
        })
print(json.dumps(out[:30], indent=2, ensure_ascii=False))
db.close()
