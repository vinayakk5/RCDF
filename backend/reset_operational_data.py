import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine
from sqlalchemy import text
from seed_masters import seed_masters

def reset_operational_data():
    print("Clearing operational tables...")
    operational_tables = [
        "bills",
        "busy_staging_bills",
        "dispatches",
        "plant_receipts",
        "plant_unloading_entries",
        "plant_unloading_masters",
        "pending_ingests",
        "purchase_orders",
        "purchase_bills",
        "sales_bills",
        "payments",
        "deals",
        "tenders",
        "sproxx_cycles",
        "main_tenders",
        "market_prices",
        "busy_exports",
        "audit_logs",
        "email_sync_logs",
        "email_sync_checkpoints",
    ]

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        for table in operational_tables:
            conn.execute(text(f"TRUNCATE TABLE {table};"))
            print(f" - Truncated table: {table}")
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

    print("\nEnsuring reference master data (Companies, 8 Plants, Materials)...")
    seed_masters()

    print("\nDatabase operational tables reset completed!")
    print("Record counts:")
    with engine.connect() as conn:
        all_tables = [
            "companies", "plants", "materials", "brokers", "busy_party_master",
            "main_tenders", "tenders", "deals", "bills", "dispatches",
            "plant_receipts", "plant_unloading_masters", "plant_unloading_entries",
            "pending_ingests", "purchase_orders", "purchase_bills", "sales_bills", "payments"
        ]
        for t in all_tables:
            cnt = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t:25s}: {cnt}")

if __name__ == "__main__":
    reset_operational_data()
