"""Versioned database migrations.

Each migration runs once and is recorded in schema_migrations. They are written to
be safe on a database that already has some of the changes (checks before each
ALTER), because older installs were patched at startup by _ensure_runtime_schema.

    cd backend
    python -m migrations status     # show applied / pending
    python -m migrations upgrade    # apply pending (also done automatically at startup)

Add a new migration: append a (version, name, function) to MIGRATIONS. Never edit
or reorder a migration that has been released.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, List, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────

def table_exists(conn: Connection, table: str) -> bool:
    return inspect(conn).has_table(table)


def column_exists(conn: Connection, table: str, column: str) -> bool:
    if not table_exists(conn, table):
        return False
    return any(c["name"] == column for c in inspect(conn).get_columns(table))


def add_column(conn: Connection, table: str, column: str, ddl: str) -> bool:
    if column_exists(conn, table, column):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    return True


def create_model_table(conn: Connection, model) -> None:
    model.__table__.create(bind=conn, checkfirst=True)


# ── migrations ─────────────────────────────────────────────────────────────

def m0001_baseline(conn: Connection) -> None:
    """Every table in models.py that does not exist yet (fresh installs)."""
    from database import Base
    import models  # noqa: F401  (registers the tables)
    Base.metadata.create_all(bind=conn, checkfirst=True)


def m0002_sales_bill_lines(conn: Connection) -> None:
    import models as m
    add_column(conn, "tenders", "sale_rate_per_qtl", "DECIMAL(10,2) NULL")
    add_column(conn, "tenders", "purchase_order_id", "INT NULL")
    add_column(conn, "sales_bills", "party_name", "VARCHAR(220) NULL")
    add_column(conn, "sales_bills", "notes", "TEXT NULL")
    add_column(conn, "sales_bills", "created_by", "VARCHAR(100) NULL")
    add_column(conn, "sales_bills", "cancelled_at", "DATETIME NULL")
    create_model_table(conn, m.SalesBillLine)
    _backfill_tender_sale_rates(conn)


def _backfill_tender_sale_rates(conn: Connection) -> None:
    """Copy the PO line rate onto tenders created from a PO before this release."""
    import json
    import re
    rows = conn.execute(text(
        "SELECT t.id, mt.name, po.line_items FROM tenders t "
        "JOIN purchase_orders po ON po.tender_id = t.id OR (po.main_tender_id = t.main_tender_id AND po.company_id = t.company_id AND (po.plant_id IS NULL OR po.plant_id = t.plant_id)) "
        "JOIN materials mt ON mt.id = t.material_id "
        "WHERE t.sale_rate_per_qtl IS NULL"
    )).fetchall()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    found = {}
    for tid, mat, items in rows:
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except ValueError:
                items = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            if norm(it.get("material_type") or it.get("material")) == norm(mat):
                try:
                    rate = float(it.get("approved_rate_per_qtl") or it.get("rate_per_qtl") or 0)
                except (TypeError, ValueError):
                    rate = 0
                if rate > 0:
                    found.setdefault(tid, set()).add(rate)
    for tid, rates in found.items():
        if len(rates) == 1:   # two different rates: leave it for the person to set
            conn.execute(text("UPDATE tenders SET sale_rate_per_qtl = :r WHERE id = :i"), {"r": rates.pop(), "i": tid})


def m0003_auto_approval(conn: Connection) -> None:
    import models as m
    create_model_table(conn, m.AutoApprovalDecision)


def m0004_users_and_sessions(conn: Connection) -> None:
    import models as m
    create_model_table(conn, m.User)
    create_model_table(conn, m.UserSession)


MIGRATIONS: List[Tuple[str, str, Callable[[Connection], None]]] = [
    ("0001", "baseline: create missing tables", m0001_baseline),
    ("0002", "sales bill lines and tender sale rate", m0002_sales_bill_lines),
    ("0003", "auto-approval decisions", m0003_auto_approval),
    ("0004", "users and login sessions", m0004_users_and_sessions),
]


# ── runner ─────────────────────────────────────────────────────────────────

def _ensure_version_table(conn: Connection) -> None:
    import models as m
    create_model_table(conn, m.SchemaMigration)


def applied_versions(engine: Engine) -> set:
    with engine.begin() as conn:
        _ensure_version_table(conn)
        return {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}


def pending(engine: Engine) -> List[Tuple[str, str]]:
    done = applied_versions(engine)
    return [(v, n) for v, n, _ in MIGRATIONS if v not in done]


def upgrade(engine: Engine) -> List[str]:
    """Apply every pending migration in order, each in its own transaction."""
    done = applied_versions(engine)
    ran = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        log.info("Applying migration %s: %s", version, name)
        with engine.begin() as conn:
            fn(conn)
            conn.execute(text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, :t)"),
                         {"v": version, "n": name, "t": datetime.now()})
        ran.append(version)
    return ran
