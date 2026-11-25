"""
Seed 849 Busy Master Parties from File1.xls into busy_party_master table.
"""
import sys, os
from pathlib import Path
import openpyxl, io
from io import BytesIO

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from database import engine, SessionLocal
from models import BusyPartyMaster, Company
from main import _read_busy_party_master_rows, _clean_gstin
from sqlalchemy import select

def seed():
    excel_path = Path(__file__).resolve().parents[1] / "File1.xls"
    if not excel_path.exists():
        excel_path = Path("File1.xls")
    
    print(f"Reading Busy Master file: {excel_path}")
    raw_bytes = excel_path.read_bytes()
    
    rows = _read_busy_party_master_rows(raw_bytes, source_file="File1.xls")
    print(f"Parsed {len(rows)} party master rows from Excel.")
    
    db = SessionLocal()
    try:
        # Check companies
        shree_nath = db.execute(select(Company).where(Company.name.ilike("%Shree Nath%"))).scalar_one_or_none()
        company_id = shree_nath.id if shree_nath else 2
        print(f"Associating with Company ID {company_id} ({shree_nath.name if shree_nath else 'Shree Nath Industries'})")

        existing_rows = db.execute(select(BusyPartyMaster).where(BusyPartyMaster.company_id == company_id)).scalars().all()
        existing_by_key = {
            (str(r.name_normalized or "").strip(), _clean_gstin(r.gstin)): r
            for r in existing_rows
            if str(r.name_normalized or "").strip()
        }

        inserted = 0
        updated = 0

        for item in rows:
            name_norm = str(item.get("name_normalized") or "").strip()
            gstin_clean = _clean_gstin(item.get("gstin"))
            key = (name_norm, gstin_clean)
            
            row = existing_by_key.get(key)
            if row:
                row.busy_party_name = item.get("busy_party_name")
                row.alias = item.get("alias")
                row.parent_group = item.get("parent_group")
                row.dealer_type = item.get("dealer_type")
                row.gstin = item.get("gstin")
                row.filing_frequency = item.get("filing_frequency")
                row.state_code = item.get("state_code")
                row.state_name = item.get("state_name")
                row.station = item.get("station")
                row.name_normalized = name_norm
                row.source_file = item.get("source_file")
                row.is_active = True
                updated += 1
            else:
                row = BusyPartyMaster(
                    company_id=company_id,
                    busy_party_name=item.get("busy_party_name"),
                    alias=item.get("alias"),
                    parent_group=item.get("parent_group"),
                    dealer_type=item.get("dealer_type"),
                    gstin=item.get("gstin"),
                    filing_frequency=item.get("filing_frequency"),
                    state_code=item.get("state_code"),
                    state_name=item.get("state_name"),
                    station=item.get("station"),
                    name_normalized=name_norm,
                    source_file=item.get("source_file"),
                    is_active=True,
                )
                db.add(row)
                inserted += 1

        db.commit()
        print(f"Successfully seeded Busy Party Masters! Inserted: {inserted}, Updated: {updated}, Total: {len(rows)}")

        # Also count active in DB
        count = db.execute(select(BusyPartyMaster).where(BusyPartyMaster.company_id == company_id, BusyPartyMaster.is_active == True)).scalars().all()
        print(f"Active party masters in DB for company {company_id}: {len(count)}")

    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
