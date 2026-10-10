"""SQLite storage for Couch Verdict.

Note: Streamlit Community Cloud containers are ephemeral — the database is
wiped when the app restarts. It powers live activity statistics for the
running instance; it is not permanent global history.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager

import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "couch_verdict.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS movie_nights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    preferences TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    night_id INTEGER REFERENCES movie_nights(id),
    movie_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    match_label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    night_id INTEGER REFERENCES movie_nights(id),
    movie_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    choice TEXT NOT NULL,
    voter TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(night_id, movie_id, voter)
);
CREATE TABLE IF NOT EXISTS saved_movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    movie_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    poster_path TEXT,
    year TEXT,
    providers TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, movie_id)
);
"""


@contextmanager
def _conn():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _migrate(connection) -> None:
    """Non-destructive upgrades for databases created by older versions."""
    cols = connection.execute("PRAGMA table_info(votes)").fetchall()
    if not cols:
        return
    has_unique = False
    for row in connection.execute("PRAGMA index_list(votes)").fetchall():
        if row["unique"]:
            members = connection.execute(
                f"PRAGMA index_info('{row['name']}')"
            ).fetchall()
            if [m["name"] for m in members] == ["night_id", "movie_id", "voter"]:
                has_unique = True
    if not has_unique:
        connection.executescript("""
            CREATE TABLE votes_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                night_id INTEGER REFERENCES movie_nights(id),
                movie_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                choice TEXT NOT NULL,
                voter TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(night_id, movie_id, voter)
            );
            INSERT OR IGNORE INTO votes_new
                (night_id, movie_id, title, choice, voter, created_at)
            SELECT night_id, movie_id, title, choice, voter, created_at FROM votes;
            DROP TABLE votes;
            ALTER TABLE votes_new RENAME TO votes;
        """)


def init_db() -> None:
    with _conn() as connection:
        connection.executescript(_SCHEMA)
        _migrate(connection)


def upsert_user(name: str) -> int:
    with _conn() as connection:
        connection.execute("INSERT OR IGNORE INTO users (name, password_hash) VALUES (?, '')", (name,))
        row = connection.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
        return row["id"]


def _hash_password(password: str, salt: str, iterations: int) -> str:
    import hashlib

    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    )
    return digest.hex()


def register_user(name: str, password: str) -> tuple[int | None, str]:
    """Create an account with a random salt and PBKDF2 hash."""
    if not name.strip() or not password:
        return None, "Enter a name and a password."
    salt = secrets.token_hex(16)
    iterations = 240_000
    pw_hash = f"pbkdf2${iterations}${salt}${_hash_password(password, salt, iterations)}"
    with _conn() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE name = ?", (name.strip(),)
        ).fetchone()
        if existing:
            return None, "That name is taken — try signing in instead."
        cursor = connection.execute(
            "INSERT INTO users (name, password_hash) VALUES (?, ?)",
            (name.strip(), pw_hash),
        )
        return cursor.lastrowid, ""


def login_user(name: str, password: str) -> tuple[int | None, str]:
    """Verify credentials. Legacy hashes are upgraded to PBKDF2 on success."""
    with _conn() as connection:
        row = connection.execute(
            "SELECT id, password_hash FROM users WHERE name = ?", (name.strip(),)
        ).fetchone()
    if not row:
        return None, "No account with that name — create one first."
    stored = row["password_hash"] or ""
    if stored.startswith("pbkdf2$"):
        try:
            scheme, iterations, salt, digest = stored.split("$", 3)
            ok = secrets.compare_digest(
                digest, _hash_password(password, salt, int(iterations))
            )
        except (ValueError, TypeError):
            ok = False
        if not ok:
            return None, "Wrong password."
        return row["id"], ""
    # Legacy salted SHA-256 from the earlier version: verify, then upgrade.
    legacy = hashlib.sha256(
        f"couch::{name.strip()}::{password}".encode()
    ).hexdigest()
    if not secrets.compare_digest(stored, legacy):
        return None, "Wrong password."
    iterations = 240_000
    salt = secrets.token_hex(16)
    new_hash = f"pbkdf2${iterations}${salt}${_hash_password(password, salt, iterations)}"
    with _conn() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["id"])
        )
    return row["id"], ""


def create_movie_night(user_id: int, preferences: dict) -> int:
    with _conn() as connection:
        cursor = connection.execute(
            "INSERT INTO movie_nights (user_id, preferences) VALUES (?, ?)",
            (user_id, json.dumps(preferences)),
        )
        return cursor.lastrowid


def record_recommendations(night_id: int, movies: list) -> None:
    with _conn() as connection:
        connection.executemany(
            "INSERT INTO recommendations (night_id, movie_id, title, match_label) VALUES (?,?,?,?)",
            [(night_id, m.movie_id, m.title, m.match_label) for m in movies],
        )


def record_vote(night_id: int, movie_id: int, title: str, choice: str, voter: str) -> None:
    """One ballot per (night, movie, voter); changing a vote replaces it."""
    with _conn() as connection:
        connection.execute(
            """
            INSERT INTO votes (night_id, movie_id, title, choice, voter)
            VALUES (?,?,?,?,?)
            ON CONFLICT(night_id, movie_id, voter)
            DO UPDATE SET choice = excluded.choice
            """,
            (night_id, movie_id, title, choice, voter),
        )


def save_movie(user_id: int, movie_id: int, title: str, poster_path, year, providers) -> None:
    with _conn() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO saved_movies (user_id, movie_id, title, poster_path, year, providers) VALUES (?,?,?,?,?,?)",
            (user_id, movie_id, title, poster_path, year, json.dumps(providers or [])),
        )


def unsave_movie(user_id: int, movie_id: int) -> None:
    with _conn() as connection:
        connection.execute("DELETE FROM saved_movies WHERE user_id = ? AND movie_id = ?", (user_id, movie_id))


def get_saved_movies(user_id: int) -> list[sqlite3.Row]:
    with _conn() as connection:
        return connection.execute(
            "SELECT * FROM saved_movies WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def is_saved(user_id: int, movie_id: int) -> bool:
    with _conn() as connection:
        row = connection.execute(
            "SELECT 1 FROM saved_movies WHERE user_id = ? AND movie_id = ?", (user_id, movie_id)
        ).fetchone()
        return row is not None


def get_stats() -> dict:
    with _conn() as connection:
        def count(query, params=()):
            row = connection.execute(query, params).fetchone()
            return row[0] if row else 0

        return {
            "movie_nights": count("SELECT COUNT(*) FROM movie_nights"),
            "recommendations": count("SELECT COUNT(*) FROM recommendations"),
            "votes": count("SELECT COUNT(*) FROM votes"),
            "saved": count("SELECT COUNT(*) FROM saved_movies"),
            "movie_lovers": count("SELECT COUNT(*) FROM users"),
        }
