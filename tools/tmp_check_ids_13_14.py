import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from database import SessionLocal
from models import Bill
from sqlalchemy import select

db=SessionLocal()
rows=db.execute(select(Bill).where(Bill.id.in_([13,14]))).scalars().all()
print(json.dumps([{"id":b.id,"plant_name":b.plant_name,"plant_id":b.plant_id,"bill_date":str(b.bill_date) if b.bill_date else None} for b in rows],indent=2))
db.close()
