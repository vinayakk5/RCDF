import os
from pathlib import Path
import pymysql

# Load .env from repo root
env_path = Path(__file__).resolve().parents[1] / '.env'
if not env_path.exists():
    raise SystemExit('.env not found')

# Simple parse
env = {}
for ln in env_path.read_text().splitlines():
    ln = ln.strip()
    if not ln or ln.startswith('#'): continue
    if '=' not in ln: continue
    k,v = ln.split('=',1)
    env[k.strip()] = v.strip()

host = env.get('DB_HOST','localhost')
port = int(env.get('DB_PORT',3306))
db   = env.get('DB_NAME')
user = env.get('DB_USER')
pwd  = env.get('DB_PASSWORD')

print('Connecting to DB', user, '@', host, db)
conn = pymysql.connect(host=host, user=user, password=pwd, db=db, port=port, charset='utf8mb4')
cur = conn.cursor()
cur.execute('ALTER TABLE dispatches MODIFY bill_id INT NULL;')
conn.commit()
print('OK')
cur.close()
conn.close()
