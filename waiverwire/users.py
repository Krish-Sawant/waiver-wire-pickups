"""
User store backed by SQLite (a single-file, server-less SQL database from the
standard library). One `users` table: email (unique) + Argon2 password hash.

The DB file defaults to ./waiverwire.db (override with USERS_DB). Passwords are
only ever stored as Argon2 hashes. SQLite is plenty for a small self-hosted app;
the same interface (create_user / verify_user / email_exists) can be re-pointed
at Postgres later without touching the API layer.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing

from waiverwire.auth import hash_password, verify_hash


def _db_path() -> str:
    return os.getenv("USERS_DB", "waiverwire.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the users table if it doesn't exist. Safe to call repeatedly."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email           TEXT PRIMARY KEY,
                password_hash   TEXT NOT NULL,
                created_at      INTEGER NOT NULL,
                sleeper_username TEXT
            )
            """
        )
        # Migrate older DBs created before the Sleeper link was added.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "sleeper_username" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN sleeper_username TEXT")


init_db()  # ensure the table exists on import


def email_exists(email: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return row is not None


def create_user(email: str, password: str) -> None:
    """Register a new user. Raises ValueError if the email is already taken."""
    key = email.strip().lower()
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (key, hash_password(password), int(time.time())),
            )
    except sqlite3.IntegrityError:
        raise ValueError("An account with that email already exists.")


def verify_user(email: str, password: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if not row:
        return False
    return verify_hash(row["password_hash"], password)


def get_sleeper_username(email: str) -> str | None:
    """The Sleeper username this account has linked, or None if not linked yet."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT sleeper_username FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    return row["sleeper_username"] if row and row["sleeper_username"] else None


def set_sleeper_username(email: str, sleeper_username: str | None) -> None:
    """Link (or, with None, unlink) a Sleeper account to this user."""
    value = sleeper_username.strip() if sleeper_username else None
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET sleeper_username = ? WHERE email = ?",
            (value, email.strip().lower()),
        )
