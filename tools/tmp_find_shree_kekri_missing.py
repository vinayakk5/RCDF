import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from database import SessionLocal
from models import Bill
from sqlalchemy import select, func, or_

db = SessionLocal()
rows = db.execute(
    select(Bill).where(
        or_(
            func.lower(func.coalesce(Bill.broker_name, "")).like("%shree%"),
            func.lower(func.coalesce(Bill.broker_name, "")).like("%kekri%"),
            func.lower(func.coalesce(Bill.plant_name, "")).like("%kekri%")
        )
    ).order_by(Bill.id.desc()).limit(100)
).scalars().all()
out=[]
for b in rows:
    miss=[]
    if b.bill_date is None: miss.append("bill_date")
    if (b.plant_id is None) and (not str(b.plant_name or "").strip()): miss.append("plant")
    if miss:
        out.append({"id":b.id,"broker_name":b.broker_name,"plant_name":b.plant_name,"bill_date":str(b.bill_date) if b.bill_date else None,"image_path":b.image_path,"missing":miss})
print(json.dumps(out,indent=2,ensure_ascii=False))
db.close()
