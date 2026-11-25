"""Login, sessions and role-based access.

- Passwords: PBKDF2-SHA256 (standard library, no extra package).
- Sessions: random token in an HttpOnly cookie (rcdf_session) or an
  "Authorization: Bearer <token>" header; only its SHA-256 is stored.
- Machines: the Busy agent and the WhatsApp bridge send X-API-Key
  (MACHINE_API_KEY); the bridge on the same computer (127.0.0.1) needs none.
- AUTH_ENABLED=false switches login off (old behaviour), e.g. for local testing.

Roles:
  admin       everything, including users
  accountant  everything except users and /api/admin
  operator    read everything; upload/review bills, documents, plant unloading,
              dispatches, receipts, WhatsApp; no payments, sales bills, Busy
              export, tenders/deals/PO changes, deletes or admin
  viewer      read only
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import User, UserRole, UserSession

COOKIE_NAME = "rcdf_session"
PBKDF2_ITERATIONS = 260_000

# Which DB session the middleware uses (tests swap it for SQLite).
session_factory: Optional[Callable[[], Session]] = None


def auth_enabled() -> bool:
    return str(os.getenv("AUTH_ENABLED", "true")).strip().lower() not in ("0", "false", "no", "off")


def session_days() -> int:
    try:
        return max(1, int(os.getenv("AUTH_SESSION_DAYS", "7")))
    except ValueError:
        return 7


# ── passwords ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def password_problem(password: str) -> Optional[str]:
    if len(password or "") < 8:
        return "Password must be at least 8 characters"
    return None


# ── sessions ───────────────────────────────────────────────────────────────

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, user_agent: Optional[str] = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token),
                       expires_at=datetime.now() + timedelta(days=session_days()),
                       user_agent=(user_agent or "")[:255], last_seen_at=datetime.now()))
    user.last_login_at = datetime.now()
    db.flush()
    return token


def user_for_token(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    s = db.execute(select(UserSession).where(UserSession.token_hash == _token_hash(token))).scalar_one_or_none()
    if not s or s.revoked or s.expires_at < datetime.now():
        return None
    u = s.user
    if not u or not u.is_active:
        return None
    if not s.last_seen_at or (datetime.now() - s.last_seen_at) > timedelta(minutes=5):
        s.last_seen_at = datetime.now()
        db.commit()
    return u


def revoke_token(db: Session, token: Optional[str]) -> None:
    if not token:
        return
    s = db.execute(select(UserSession).where(UserSession.token_hash == _token_hash(token))).scalar_one_or_none()
    if s:
        s.revoked = True
        db.flush()


def revoke_user_sessions(db: Session, user_id: int) -> None:
    for s in db.execute(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked == False)).scalars():  # noqa: E712
        s.revoked = True
    db.flush()


def user_count(db: Session) -> int:
    return int(db.execute(select(func.count(User.id))).scalar() or 0)


# ── login throttling (per username + IP, in memory) ────────────────────────

_FAILS: dict = {}
MAX_FAILS = 5
LOCK_SECONDS = 300


def login_locked(key: str) -> bool:
    fails, since = _FAILS.get(key, (0, 0.0))
    if fails >= MAX_FAILS and time.time() - since < LOCK_SECONDS:
        return True
    if fails >= MAX_FAILS:
        _FAILS.pop(key, None)
    return False


def record_login_failure(key: str) -> None:
    fails, since = _FAILS.get(key, (0, time.time()))
    _FAILS[key] = (fails + 1, since if fails else time.time())


def clear_login_failures(key: str) -> None:
    _FAILS.pop(key, None)


# ── access rules ───────────────────────────────────────────────────────────

PUBLIC_PATHS = {
    "/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/bootstrap",
    "/api/telegram/webhook",   # Telegram's servers call this
}
MACHINE_ONLY_ALLOWED = [
    re.compile(r"^/api/export/[a-z-]+/busy-xlsx$"),
    re.compile(r"^/api/busy/"),
    re.compile(r"^/api/whatsapp/webhook$"),
]
LOOPBACK_ALLOWED = [re.compile(r"^/api/whatsapp/webhook$")]

ADMIN_ONLY = [re.compile(r"^/api/admin/"), re.compile(r"^/api/auth/users"), re.compile(r"^/whatsapp-qr"),
              re.compile(r"^/api/telegram/set-webhook"), re.compile(r"^/api/download/busy-agent-pkg")]

OPERATOR_WRITE_ALLOWED = [
    re.compile(p) for p in (
        r"^/api/bills(/|$)", r"^/api/ingest(/|$)", r"^/api/plant-unloading(/|$)",
        r"^/api/receipts(/|$)", r"^/api/dispatch", r"^/api/busy-staging(/|$)",
        r"^/api/whatsapp(/|$)", r"^/api/market-prices(/|$)", r"^/api/auth/password$",
    )
]
OPERATOR_WRITE_DENIED = [re.compile(r"/delete$"), re.compile(r"/bulk-delete$")]

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_protected_path(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/uploads/") or path.startswith("/whatsapp-qr")


def role_allows(role: UserRole, method: str, path: str) -> bool:
    method = method.upper()
    if role == UserRole.admin:
        return True
    if any(p.search(path) for p in ADMIN_ONLY):
        return False
    if role == UserRole.accountant:
        return True
    if path.startswith("/api/export/"):
        return False   # exports mark records as sent to Busy, even on GET
    if method in READ_METHODS:
        return True
    if role == UserRole.viewer:
        return path == "/api/auth/password"
    # operator
    if method == "DELETE" or any(p.search(path) for p in OPERATOR_WRITE_DENIED):
        return False
    return any(p.search(path) for p in OPERATOR_WRITE_ALLOWED)


def machine_key_ok(header_value: Optional[str]) -> bool:
    key = os.getenv("MACHINE_API_KEY", "").strip()
    return bool(key) and bool(header_value) and hmac.compare_digest(key, header_value.strip())


def check_request(method: str, path: str, token: Optional[str], api_key: Optional[str],
                  client_host: Optional[str], db_factory: Callable[[], Session]) -> Tuple[int, Optional[User], str]:
    """Decide one request. Returns (http_status, user, message); 200 means allowed."""
    if not auth_enabled() or not is_protected_path(path) or path in PUBLIC_PATHS:
        return 200, None, ""
    if any(p.search(path) for p in MACHINE_ONLY_ALLOWED) and machine_key_ok(api_key):
        return 200, None, "machine"
    if any(p.search(path) for p in LOOPBACK_ALLOWED) and client_host in ("127.0.0.1", "::1", "localhost"):
        return 200, None, "loopback"
    with db_factory() as db:
        user = user_for_token(db, token)
        if user is None:
            return 401, None, "Please log in"
        db.expunge(user)
    if not role_allows(user.role, method, path):
        return 403, user, f"Your role ({user.role.value}) cannot do this"
    return 200, user, ""
