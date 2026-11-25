"""
RCDF Operations Platform — Lightweight Windows 7 Busy Auto-Import Agent
Designed specifically for Windows 7 with low RAM (< 10 MB RAM footprint).
Zero external dependencies (uses standard Python 3.x library only).

How it works:
1. Polls the RCDF platform for approved, verified purchase bills.
2. Automatically downloads the Busy-formatted Book1.xlsx voucher file
   directly into Busy's import directory.
3. Automatically creates a backup with timestamp.
4. When the accountant opens Busy -> Administration -> Data Export/Import ->
   Import Vouchers from Excel, the latest verified vouchers are ready for 1-click import!
"""

import os
import sys
import time
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Configure logging
LOG_FILE = Path(__file__).resolve().parent / "busy_agent.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("BusyWin7Agent")

CONFIG_FILE = Path(__file__).resolve().parent / "busy_agent_config.json"

DEFAULT_CONFIG = {
    "server_url": "http://147.93.106.168:8000",
    "company_id": 2,
    "company_name": "Shree Nath Industries",
    "busy_import_dir": "C:\\BusyWin\\Import",
    "import_filename": "Book1.xlsx",
    "poll_interval_seconds": 60,
    "auto_backup": True,
    "api_key": ""
}

def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                config.update(user_cfg)
        except Exception as e:
            log.warning(f"Could not load {CONFIG_FILE}: {e}. Using defaults.")
    else:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            log.info(f"Created default configuration at {CONFIG_FILE}")
        except Exception as e:
            log.warning(f"Could not create {CONFIG_FILE}: {e}")
    return config

def fetch_pending_busy_vouchers(config: dict) -> bool:
    server = config.get("server_url", "http://127.0.0.1:8000").rstrip("/")
    comp_id = config.get("company_id", 2)
    import_dir = Path(config.get("busy_import_dir", "C:\\BusyWin\\Import"))
    filename = config.get("import_filename", "Book1.xlsx")

    try:
        import_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.error(f"Cannot create or access Busy import directory {import_dir}: {e}")
        return False

    url = f"{server}/api/export/purchase-bills/busy-xlsx?company_id={comp_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RCDF-Busy-Win7-Agent/1.0",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
    )

    try:
        log.debug(f"Checking for new approved vouchers from {url}...")
        with urllib.request.urlopen(req, timeout=25) as resp:
            if resp.status == 200:
                content = resp.read()
                # Check if file has content
                if len(content) < 100:
                    return False

                target_file = import_dir / filename
                
                # Check if content changed
                if target_file.exists():
                    existing_bytes = target_file.read_bytes()
                    if existing_bytes == content:
                        return False # No new vouchers

                # Write new Book1.xlsx
                target_file.write_bytes(content)
                log.info(f">>> NEW VOUCHERS DOWNLOADED: {target_file} ({len(content)} bytes)")

                # Auto-backup
                if config.get("auto_backup", True):
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_dir = import_dir / "Backups"
                    backup_dir.mkdir(exist_ok=True)
                    backup_path = backup_dir / f"Book1_{ts}.xlsx"
                    backup_path.write_bytes(content)
                    log.info(f"    Voucher backup saved: {backup_path}")

                return True
    except urllib.error.HTTPError as he:
        if he.code == 404 or he.code == 400:
            log.debug(f"Server response {he.code}: No pending exportable vouchers.")
        else:
            log.warning(f"Server HTTP {he.code}: {he.reason}")
    except Exception as e:
        log.warning(f"Connection check failed: {e}")

    return False

def main():
    print("=" * 60)
    print(" RCDF Operations Platform — Windows 7 Busy Auto-Import Agent")
    print(" Ultra-Lightweight Background Voucher Sync (<10 MB RAM)")
    print("=" * 60)

    config = load_config()
    print(f" Server URL       : {config.get('server_url')}")
    print(f" Company Target   : {config.get('company_name')} (ID: {config.get('company_id')})")
    print(f" Busy Import Dir  : {config.get('busy_import_dir')}")
    print(f" Target Filename  : {config.get('import_filename')}")
    print(f" Poll Interval    : {config.get('poll_interval_seconds')} seconds")
    print(f" Logging To       : {LOG_FILE}")
    print("-" * 60)
    print("Agent is active and monitoring. Press Ctrl+C to exit.\n")

    while True:
        try:
            fetch_pending_busy_vouchers(config)
        except Exception as e:
            log.error(f"Unexpected loop error: {e}")

        time.sleep(int(config.get("poll_interval_seconds", 60)))

if __name__ == "__main__":
    main()
