import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine
from sqlalchemy import text

def seed_masters():
    with engine.begin() as conn:
        # 1. Seed & Normalize Companies
        companies_seed = [
            (1, "Shree Ganpati Enterprises"),
            (2, "Shree Nath Industries"),
            (3, "Shree Vinayak Trading Company")
        ]
        for c_id, c_name in companies_seed:
            conn.execute(text("""
                INSERT INTO companies (id, name, is_active, created_at)
                VALUES (:id, :name, 1, NOW())
                ON DUPLICATE KEY UPDATE name = :name, is_active = 1
            """), {"id": c_id, "name": c_name})
        
        conn.execute(text("UPDATE companies SET is_active = 1"))

        # 2. Seed 8 Official Plants
        plants = [
            ("Jodhpur", "JDH"),
            ("Kaladera", "KLD"),
            ("Nadbai", "NDB"),
            ("Ajmer", "AJM"),
            ("Pali", "PLI"),
            ("Bikaner", "BKN"),
            ("Lambiya", "LMB"),
            ("Bhilwara", "BHW")
        ]
        for p_name, p_code in plants:
            conn.execute(text("""
                INSERT INTO plants (name, code, is_active)
                VALUES (:name, :code, 1)
                ON DUPLICATE KEY UPDATE code = :code, is_active = 1
            """), {"name": p_name, "code": p_code})
        
        # Standardize Lambiyan -> Lambiya
        conn.execute(text("UPDATE plants SET name = 'Lambiya' WHERE LOWER(name) LIKE '%lambiya%'"))

        # 3. Seed Materials
        materials = [
            ("Maize", "MZ", "MT"),
            ("Dorb", "DB", "MT"),
            ("Domc", "DM", "MT"),
            ("Rice DDGS", "RD", "MT"),
            ("Rice Bran", "RB", "MT"),
            ("Gawar Korma", "GK", "MT"),
            ("Molasses", "ML", "MT")
        ]
        for m_name, m_code, m_unit in materials:
            conn.execute(text("""
                INSERT INTO materials (name, code, unit, is_active)
                VALUES (:name, :code, :unit, 1)
                ON DUPLICATE KEY UPDATE code = :code, unit = :unit, is_active = 1
            """), {"name": m_name, "code": m_code, "unit": m_unit})

    with engine.connect() as conn:
        print("--- COMPANIES ---")
        for r in conn.execute(text("SELECT id, name FROM companies")).mappings():
            print(dict(r))
        print("\n--- PLANTS ---")
        for r in conn.execute(text("SELECT id, name, code FROM plants")).mappings():
            print(dict(r))
        print("\n--- MATERIALS ---")
        for r in conn.execute(text("SELECT id, name, code FROM materials")).mappings():
            print(dict(r))

if __name__ == "__main__":
    seed_masters()
