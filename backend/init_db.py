import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine
from models import Base

print("1. Creating database tables via SQLAlchemy metadata...")
Base.metadata.create_all(bind=engine)

print("2. Applying versioned migrations...")
import migrations
print("   applied:", migrations.upgrade(engine) or "none needed")

print("2b. Ensuring runtime schema tables & columns...")
from main import _ensure_runtime_schema
_ensure_runtime_schema()

print("3. Seeding reference master data...")
from seed_masters import seed_masters
seed_masters()

print("\nSUCCESS: Database initialized and seeded successfully!")
