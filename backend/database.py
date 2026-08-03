from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
import os

class Settings(BaseSettings):
    db_host:     str = "localhost"
    db_port:     int = 3306
    db_name:     str = "rcdf_supply"
    db_user:     str = "root"
    db_password: str = "password"
    host:        str = "0.0.0.0"
    port:        int = 8000
    debug:       bool = True
    telegram_token:      str = ""
    webhook_url:         str = ""
    gemini_api_key:      str = ""
    
    # --- New Google Cloud Document AI Settings ---
    gcp_project_id:      Optional[str] = None
    gcp_processor_id:    Optional[str] = None
    gcp_location:        str = "us"
    # ---------------------------------------------
    
    ocr_confidence_threshold: float = 0.85
    upload_dir:  str = "./uploads"
    busy_export_dir: str = "./busy_exports"
    company_name:  str = "RCDF Supply Co."
    company_gstin: str = ""
    email_host:  str = "imap.gmail.com"
    email_user:  str = ""
    email_pass:  str = ""
    email_sync_auto_enabled: bool = True
    email_sync_runs_per_day: int = 4
    email_sync_limit: int = 80
    # Default to syncing both read and unread emails.
    email_sync_unread_only: bool = False
    email_sync_mark_seen: bool = False
    email_sync_mailbox: str = "INBOX"
    # Comma-separated sender email IDs allowed for ingest.
    # Empty means allow all senders.
    email_sync_allowed_senders: str = "cfpjdh-rcdf-rj@nic.in,cfppaliskrm@gmail.com,cattlefeedkaladera@gmail.com,md-rcdf@rajasthan.gov.in,cfpbkn@gmail.com,cfpbik-rcdf-rj@nic.in,rcdfcf_ajm1@rediffmail.com,cfpjdh@gmail.com,cfplambiya@gmail.com,cfp.kaladera@gmail.com,cfppali@gmail.com,pur-rcdf-rj@gov.in,pur-rcdf-rj@nic.in,fa-rcdf-rj@nic.in,pa-rcdf@rajasthan.gov.in,cfpnadbai786@gmail.com,cfpndb-rcdf-rj@nic.in"

    # Optionally configure multiple email accounts to sync. Format: entries separated by ';'
    # each entry is 'email|password' or 'email|password|mailbox' or 'email|password|mailbox|host'.
    # Example:
    # "a@example.com|pass; b@example.com|pass|INBOX; c@yahoodomain.com|pass|INBOX|imap.mail.yahoo.com"
    email_sync_accounts: str = ""
    

    # Allow extra environment variables (some deployments set extra keys)
    model_config = {
        'env_file': '.env',
        'case_sensitive': False,
        'extra': 'ignore'
    }

@lru_cache
def get_settings() -> Settings:
    return Settings()

from urllib.parse import quote_plus

def get_db_url() -> str:
    s = get_settings()
    user = quote_plus(s.db_user or "")
    pwd = quote_plus(s.db_password or "")
    return f"mysql+pymysql://{user}:{pwd}@{s.db_host}:{s.db_port}/{s.db_name}?charset=utf8mb4"

engine = create_engine(
    get_db_url(),
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_dirs():
    s = get_settings()
    os.makedirs(s.upload_dir,      exist_ok=True)
    os.makedirs(s.busy_export_dir, exist_ok=True)
    os.makedirs("./uploads/bills", exist_ok=True)