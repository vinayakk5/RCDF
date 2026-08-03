import sys
sys.path.append('.')
import sqlalchemy as sa
from backend.database import engine
with engine.connect() as conn:
    res = conn.execute(sa.text("SELECT IS_NULLABLE, COLUMN_TYPE FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name='dispatches' AND column_name='bill_id'"))
    for row in res:
        print(row)
