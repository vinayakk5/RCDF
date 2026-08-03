from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from database import SessionLocal, get_settings
from models import IngestSource, PendingIngest, PurchaseOrder


def _abs_pending_path(upload_dir: str, rel_or_abs: str) -> Path:
    p = Path(str(rel_or_abs or "").strip())
    if p.is_absolute():
        return p
    return (Path(upload_dir) / p).resolve()


def main() -> None:
    db = SessionLocal()
    summary = {
        "checkpoint_rows_deleted": 0,
        "email_pending_deleted": 0,
        "purchase_orders_unlinked": 0,
        "files_deleted": 0,
        "file_delete_errors": 0,
    }

    try:
        settings = get_settings()
        upload_dir = str(settings.upload_dir)

        email_rows = db.query(PendingIngest).filter(PendingIngest.source == IngestSource.email).all()
        pending_ids = [r.id for r in email_rows]
        file_paths = [r.file_path for r in email_rows if r.file_path]

        if pending_ids:
            summary["purchase_orders_unlinked"] = int(
                db.query(PurchaseOrder)
                .filter(PurchaseOrder.source_pending_id.in_(pending_ids))
                .update({"source_pending_id": None}, synchronize_session=False)
                or 0
            )
            summary["email_pending_deleted"] = int(
                db.query(PendingIngest)
                .filter(PendingIngest.id.in_(pending_ids))
                .delete(synchronize_session=False)
                or 0
            )

        summary["checkpoint_rows_deleted"] = int(
            db.execute(text("DELETE FROM email_sync_checkpoints")).rowcount or 0
        )
        db.commit()

        for rel in file_paths:
            try:
                abs_path = _abs_pending_path(upload_dir, rel)
                if abs_path.exists() and abs_path.is_file():
                    abs_path.unlink()
                    summary["files_deleted"] += 1
            except Exception:
                summary["file_delete_errors"] += 1

        print("EMAIL_SYNC_RESET_OK")
        for k, v in summary.items():
            print(f"{k}={v}")
    except Exception as e:
        db.rollback()
        print("EMAIL_SYNC_RESET_FAILED")
        print(str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
