import os
from pathlib import Path
from dotenv import load_dotenv
import pymysql

root = Path(__file__).resolve().parents[1]
load_dotenv(root / '.env')

DB_HOST = os.getenv('DB_HOST','localhost')
DB_PORT = int(os.getenv('DB_PORT','3306'))
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

print('Connecting to', DB_USER, '@', DB_HOST, DB_NAME)
conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, db=DB_NAME, port=DB_PORT, charset='utf8mb4')
cur = conn.cursor()
# Add columns if not exist (MySQL compatible syntax tolerant)
stmts = [
    "ALTER TABLE dispatches ADD COLUMN is_deleted TINYINT(1) DEFAULT 0;",
    "ALTER TABLE dispatches ADD COLUMN deleted_at DATETIME NULL;",
    "ALTER TABLE plant_receipts ADD COLUMN is_deleted TINYINT(1) DEFAULT 0;",
    "ALTER TABLE plant_receipts ADD COLUMN deleted_at DATETIME NULL;",
    "CREATE TABLE IF NOT EXISTS audit_logs (id INT PRIMARY KEY AUTO_INCREMENT, entity VARCHAR(100) NOT NULL, entity_id INT NOT NULL, action VARCHAR(50) NOT NULL, payload JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
]
for s in stmts:
    try:
        cur.execute(s)
        print('OK:', s)
    except Exception as e:
        print('WARN:', e)
conn.commit()
cur.close()
conn.close()
print('Migration done')
