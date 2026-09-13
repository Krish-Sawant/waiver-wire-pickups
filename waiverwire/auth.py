"""
Auth primitives: Argon2 password hashing + signed (JWT) session tokens.

Passwords are HASHED with Argon2 (one-way) — never stored reversibly. User
accounts live in the user store (see users.py); this module just provides the
hashing, token minting, and the request auth gate.

Configure in .env:
    AUTH_SECRET=<random string>   # signs session tokens; keep it secret
"""

from __future__ import annotations

import os
import secrets
import time

import jwt
from argon2 import PasswordHasher
from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

_ph = PasswordHasher()
# If no secret is set, use a per-process random one (sessions won't survive a
# restart — set AUTH_SECRET in .env for stable logins).
AUTH_SECRET = os.getenv("AUTH_SECRET") or secrets.token_hex(32)
_TOKEN_HOURS = 24


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_hash(stored_hash: str, password: str) -> bool:
    """True if `password` matches the stored Argon2 hash."""
    try:
        return _ph.verify(stored_hash, password)
    except Exception:
        return False


def create_token(subject: str) -> str:
    payload = {"sub": subject, "exp": int(time.time()) + _TOKEN_HOURS * 3600}
    return jwt.encode(payload, AUTH_SECRET, algorithm="HS256")


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency — the auth gate. Rejects any request without a valid
    Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(authorization[7:], AUTH_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")
    return str(payload.get("sub", ""))
