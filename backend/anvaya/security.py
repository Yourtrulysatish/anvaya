"""Authentication, session management and API rate limiting."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .db import get_store, new_id

SESSION_TTL = 60 * 60 * 24 * 7
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def hash_password(pw: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
        new = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(new.hex(), dk)
    except Exception:
        return False


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register(email: str, password: str) -> dict:
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(400, "Invalid email address")
    if len(password) < 10 or len(password) > 200:
        raise HTTPException(400, "Password must be 10-200 characters")
    store = get_store()
    if store.execute("SELECT 1 FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "An account with this email already exists")
    uid = new_id("usr")
    store.execute("INSERT INTO users(id,email,pw_hash,created) VALUES(?,?,?,?)", (uid, email, hash_password(password), time.time()))
    return {"id": uid, "email": email}


def login(email: str, password: str) -> dict:
    rows = get_store().execute("SELECT id,email,pw_hash FROM users WHERE email=?", (email.strip().lower(),))
    if not rows or not verify_password(password, rows[0]["pw_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = secrets.token_urlsafe(32)
    get_store().execute("INSERT INTO sessions(token_hash,user_id,expires) VALUES(?,?,?)", (_th(token), rows[0]["id"], time.time() + SESSION_TTL))
    return {"token": token, "user": {"id": rows[0]["id"], "email": rows[0]["email"]}, "expires_in": SESSION_TTL}


def logout(token: str) -> None:
    get_store().execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


def _token_from(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def current_user(request: Request) -> dict:
    token = _token_from(request)
    if not token:
        raise HTTPException(401, "Authentication required")
    rows = get_store().execute(
        "SELECT u.id,u.email FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?", (_th(token), time.time()))
    if not rows:
        raise HTTPException(401, "Session expired or invalid")
    return {"id": rows[0]["id"], "email": rows[0]["email"], "token": token}


User = Depends(current_user)


def own_project(pid: str, user: dict) -> dict:
    p = get_store().get("project", pid)
    if not p or p["_owner"] != user["id"]:
        raise HTTPException(404, "Project not found")   # 404 (not 403) so ids can't be probed
    return p


def own_simulation(sid: str, user: dict) -> dict:
    s = get_store().get("simulation", sid)
    if not s:
        raise HTTPException(404, "Simulation not found")
    own_project(s["_project"], user)
    return s


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window per client IP. Sized for a single-worker deployment."""
    def __init__(self, app, general: int = 300, auth: int = 12, heavy: int = 30):
        super().__init__(app)
        self.limits = {"general": general, "auth": auth, "heavy": heavy}
        self.hits: dict = defaultdict(deque)

    def _bucket(self, request: Request) -> str:
        p = request.url.path
        if p.startswith("/api/auth/"):
            return "auth"
        if request.method == "POST" and any(k in p for k in ("/generate", "/simulations", "/scenarios", "/reports", "/analyse", "/recommendations", "/interview")):
            return "heavy"
        return "general"

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS" or request.url.path.endswith("/stream"):
            return await call_next(request)
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
        b = self._bucket(request)
        q = self.hits[(ip, b)]
        now = time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limits[b]:
            return JSONResponse({"detail": "Rate limit exceeded. Slow down."}, status_code=429, headers={"Retry-After": "30"})
        q.append(now)
        return await call_next(request)
