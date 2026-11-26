"""Login, roles and versioned migrations (SQLite, no MySQL needed)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import models as m
import main
import migrations
from services import auth


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

        def _db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = _db
        auth.session_factory = self.Session
        auth._FAILS.clear()
        self.env = mock.patch.dict(os.environ, {"AUTH_ENABLED": "true", "MACHINE_API_KEY": "agent-key-123"})
        self.env.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.env.stop()
        main.app.dependency_overrides.clear()
        auth.session_factory = None
        self.engine.dispose()

    def make_user(self, username, role, password="secret-pass-1"):
        with self.Session() as db:
            db.add(m.User(username=username, password_hash=auth.hash_password(password), role=m.UserRole(role)))
            db.commit()

    def login(self, username, password="secret-pass-1"):
        c = TestClient(main.app)
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        return c

    def test_api_needs_login(self):
        self.assertEqual(self.client.get("/api/plants").status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 200)        # login page itself is public

    def test_first_admin_bootstrap_only_once(self):
        me = self.client.get("/api/auth/me").json()
        self.assertTrue(me["needs_first_admin"])
        r = self.client.post("/api/auth/bootstrap", json={"username": "vinu", "password": "long-enough-1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["user"]["role"], "admin")
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["username"], "vinu")
        r2 = TestClient(main.app).post("/api/auth/bootstrap", json={"username": "x", "password": "long-enough-2"})
        self.assertEqual(r2.status_code, 403)

    def test_wrong_password_and_lockout(self):
        self.make_user("acc", "accountant")
        for _ in range(5):
            r = self.client.post("/api/auth/login", json={"username": "acc", "password": "nope"})
            self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/auth/login", json={"username": "acc", "password": "secret-pass-1"})
        self.assertEqual(r.status_code, 429)

    def test_roles(self):
        self.make_user("view", "viewer")
        self.make_user("op", "operator")
        self.make_user("acc", "accountant")
        viewer, op, acc = self.login("view"), self.login("op"), self.login("acc")
        self.assertEqual(viewer.get("/api/plants").status_code, 200)
        self.assertEqual(viewer.post("/api/payments", json={}).status_code, 403)
        # operator may review bills but not pay, bill plants, export or delete
        self.assertNotEqual(op.patch("/api/bills/999/approve").status_code, 403)
        self.assertEqual(op.post("/api/payments", json={}).status_code, 403)
        self.assertEqual(op.post("/api/sales-bills", json={"receipt_ids": [1]}).status_code, 403)
        self.assertEqual(op.get("/api/export/sales-bills/busy-xlsx").status_code, 403)
        self.assertEqual(op.delete("/api/bills/1").status_code, 403)
        # accountant may pay but not manage users
        self.assertNotEqual(acc.post("/api/payments", json={}).status_code, 403)
        self.assertEqual(acc.get("/api/auth/users").status_code, 403)

    def test_admin_manages_users_and_keeps_one_admin(self):
        self.make_user("boss", "admin")
        boss = self.login("boss")
        r = boss.post("/api/auth/users", json={"username": "ram", "password": "ram-pass-123", "role": "operator"})
        self.assertEqual(r.status_code, 200, r.text)
        uid = r.json()["id"]
        self.assertEqual(boss.patch(f"/api/auth/users/{uid}", json={"role": "accountant"}).json()["role"], "accountant")
        me_id = boss.get("/api/auth/me").json()["user"]["id"]
        self.assertEqual(boss.patch(f"/api/auth/users/{me_id}", json={"role": "viewer"}).status_code, 400)
        # deactivating a user ends their sessions
        ram = self.login("ram", "ram-pass-123")
        boss.patch(f"/api/auth/users/{uid}", json={"is_active": False})
        self.assertEqual(ram.get("/api/plants").status_code, 401)

    def test_logout(self):
        self.make_user("acc", "accountant")
        c = self.login("acc")
        self.assertEqual(c.get("/api/plants").status_code, 200)
        c.post("/api/auth/logout")
        self.assertEqual(c.get("/api/plants").status_code, 401)

    def test_bearer_token_and_machine_key(self):
        self.make_user("acc", "accountant")
        token = self.client.post("/api/auth/login", json={"username": "acc", "password": "secret-pass-1"}).json()["token"]
        fresh = TestClient(main.app)
        self.assertEqual(fresh.get("/api/plants", headers={"Authorization": f"Bearer {token}"}).status_code, 200)
        # Busy agent: key opens only its export endpoints
        r = fresh.get("/api/export/sales-bills/busy-xlsx", headers={"X-API-Key": "agent-key-123"})
        self.assertNotIn(r.status_code, (401, 403))
        self.assertEqual(fresh.get("/api/plants", headers={"X-API-Key": "agent-key-123"}).status_code, 401)
        self.assertEqual(fresh.get("/api/export/sales-bills/busy-xlsx", headers={"X-API-Key": "wrong"}).status_code, 401)

    def test_auth_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {"AUTH_ENABLED": "false"}):
            self.assertEqual(self.client.get("/api/plants").status_code, 200)


class PasswordTests(unittest.TestCase):
    def test_hash_roundtrip(self):
        h = auth.hash_password("abc12345")
        self.assertTrue(auth.verify_password("abc12345", h))
        self.assertFalse(auth.verify_password("abc12346", h))
        self.assertNotIn("abc12345", h)


class MigrationTests(unittest.TestCase):
    def test_upgrade_old_database_then_noop(self):
        engine = sa.create_engine("sqlite://")
        # An old install: tables exist but without this release's columns/tables.
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE tenders (id INTEGER PRIMARY KEY, company_id INT, main_tender_id INT, plant_id INT, material_id INT)"))
            conn.execute(sa.text("CREATE TABLE sales_bills (id INTEGER PRIMARY KEY, sb_number VARCHAR(50))"))
            conn.execute(sa.text("CREATE TABLE materials (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
            conn.execute(sa.text("CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY, company_id INT, main_tender_id INT, tender_id INT, plant_id INT, line_items JSON)"))
            conn.execute(sa.text("INSERT INTO materials VALUES (1, 'Maize')"))
            conn.execute(sa.text("INSERT INTO tenders VALUES (1, 1, 1, 1, 1)"))
            conn.execute(sa.text("""INSERT INTO purchase_orders VALUES (1, 1, 1, 1, 1, '[{"material_type": "Maize", "approved_rate_per_qtl": 2650}]')"""))
        ran = migrations.upgrade(engine)
        self.assertEqual(ran, ["0001", "0002", "0003", "0004", "0005"])
        with engine.connect() as conn:
            self.assertTrue(migrations.column_exists(conn, "tenders", "sale_rate_per_qtl"))
            self.assertTrue(migrations.column_exists(conn, "sales_bills", "party_name"))
            for t in ("sales_bill_lines", "auto_approval_decisions", "users", "user_sessions"):
                self.assertTrue(migrations.table_exists(conn, t), t)
            rate = conn.execute(sa.text("SELECT sale_rate_per_qtl FROM tenders WHERE id = 1")).scalar()
        self.assertEqual(float(rate), 2650)
        self.assertEqual(migrations.upgrade(engine), [])
        self.assertEqual(migrations.pending(engine), [])


if __name__ == "__main__":
    unittest.main()
