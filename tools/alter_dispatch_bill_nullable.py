from backend.database import engine
with engine.connect() as conn:
    conn.execute("ALTER TABLE dispatches MODIFY bill_id INT NULL;")
    conn.commit()
    print('OK')
