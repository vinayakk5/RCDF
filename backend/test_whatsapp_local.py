import os
import sys
import asyncio
from datetime import datetime

# Configure UTF-8 for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from database import engine, SessionLocal
from models import Base, WhatsAppConfig, WhatsAppLog, Bill, Company, Plant, Material, Broker
from services.whatsapp_service import handle_whatsapp_webhook

def test_local_whatsapp_pipeline():
    print("=" * 60)
    print("🚀 STARTING LOCAL WHATSAPP PIPELINE TEST")
    print("=" * 60)

    # 1. Ensure DB tables
    print("\n[Step 1] Ensuring Database Schema & Runtime Tables...")
    from main import _ensure_runtime_schema
    _ensure_runtime_schema()
    print("✅ Database schema initialized.")

    db = SessionLocal()
    try:
        # 2. Check or create test master data
        print("\n[Step 2] Verifying Reference Master Records...")
        company = db.query(Company).first()
        if not company:
            company = Company(name="RCDF Jaipur Plant Ltd", code="RCDF01", is_active=True)
            db.add(company)
            db.commit()
            db.refresh(company)
        print(f"✅ Company context: ID={company.id}, Name={company.name}")

        plant = db.query(Plant).first()
        if not plant:
            plant = Plant(name="Jaipur Central Dairy", code="JCD")
            db.add(plant)
            db.commit()
            db.refresh(plant)
        print(f"✅ Plant context: ID={plant.id}, Name={plant.name}")

        material = db.query(Material).first()
        if not material:
            material = Material(name="Maize", code="MZ")
            db.add(material)
            db.commit()
            db.refresh(material)
        print(f"✅ Material context: ID={material.id}, Name={material.name}")

        broker = db.query(Broker).first()
        if not broker:
            broker = Broker(name="Apex Agri Traders", phone="9876543210")
            db.add(broker)
            db.commit()
            db.refresh(broker)
        print(f"✅ Broker context: ID={broker.id}, Name={broker.name}")

        # Ensure WhatsAppConfig has whitelisted JID or empty whitelist
        config = db.query(WhatsAppConfig).first()
        if not config:
            config = WhatsAppConfig(is_enabled=True, auto_reply=True, whitelisted_jids=["1203630283921829@g.us", "919876543210@s.whatsapp.net"])
            db.add(config)
        else:
            config.is_enabled = True
            config.whitelisted_jids = ["1203630283921829@g.us", "919876543210@s.whatsapp.net"]
        db.commit()

        # 3. Simulate Incoming WhatsApp Purchase Bill Message
        print("\n[Step 3] Simulating Incoming WhatsApp Webhook (Media Purchase Bill)...")
        sample_msg_id = f"TEST_WA_MSG_{int(datetime.now().timestamp())}"
        test_payload = {
            "message_id": sample_msg_id,
            "chat_jid": "1203630283921829@g.us",
            "chat_name": "RCDF Maize Suppliers Group",
            "is_group": True,
            "sender_jid": "919876543210@s.whatsapp.net",
            "sender_name": "Apex Agri Traders",
            "sender_phone": "919876543210",
            "has_media": True,
            "media": {
                "filename": "sample_bill.jpg",
                "path": "uploads/whatsapp/sample_bill.jpg",
                "mimetype": "image/jpeg",
                "filesize": 12345
            },
            "text": "",
            "caption": ""
        }

        # Run ingestion handler
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(handle_whatsapp_webhook(test_payload, db))
        print(f"✅ Ingestion handler result: {res}")

        # 4. Verify Database Records
        print("\n[Step 4] Verifying Ingested Bill & WhatsApp Audit Log in DB...")
        log_entry = db.query(WhatsAppLog).filter(WhatsAppLog.message_id == sample_msg_id).first()
        assert log_entry is not None, "WhatsAppLog entry was not created!"
        print(f"✅ WhatsAppLog record: ID={log_entry.id}, DocType={log_entry.doc_type}, Status={log_entry.status}")
        print(f"   Automated Reply Generated:\n{log_entry.reply_sent}")

        if res.get("bill_id"):
            bill = db.query(Bill).filter(Bill.id == res["bill_id"]).first()
            assert bill is not None, "Bill record was not created!"
            print(f"✅ Bill record created: ID={bill.id}, Bill#={bill.bill_number}, Amount=₹{bill.total_amount}, Source={bill.source}")

        print("\n" + "=" * 60)
        print("🎉 ALL LOCAL WHATSAPP TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)

    finally:
        db.close()

if __name__ == "__main__":
    test_local_whatsapp_pipeline()
