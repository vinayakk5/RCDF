import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))

from database import SessionLocal
from services.email_sync_service import sync_email_pending_ingests

async def main():
    db = SessionLocal()
    try:
        res = await sync_email_pending_ingests(
            db,
            limit=8,
            since_days=4,
            unread_only=False,
            mark_seen=False,
            start_uid=0,
            update_checkpoint=False,
            ignore_duplicates=True,
            email_user_override="gordhan.khandelwal@yahoo.com",
            email_pass_override="bvpovqaauirekkql",
            mailbox_override="INBOX",
            host_override="imap.mail.yahoo.com",
            sync_reason="manual",
        )
        print("OK", res.get("scanned_messages"), res.get("created"), res.get("duplicates"), res.get("skipped_sender"))
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
