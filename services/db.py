"""SQLite storage for Couch Verdict.

Streamlit Community Cloud containers are ephemeral. The database powers
activity statistics and voting records for the running instance; it is not
permanent global history.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

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
    created_at TEXT DEFAULT (datetime('now'))
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


def init_db() -> None:
    with _conn() as connection:
        connection.executescript(_SCHEMA)


def upsert_user(name: str) -> int:
    with _conn() as connection:
        connection.execute("INSERT OR IGNORE INTO users (name, password_hash) VALUES (?, '')", (name,))
        row = connection.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
        return row["id"]


def hash_password(name: str, password: str) -> str:
    """Salted SHA-256 (salt = username), retained for legacy account data."""
    import hashlib
    return hashlib.sha256(f"couch::{name}::{password}".encode()).hexdigest()


def register_user(name: str, password: str) -> tuple[int | None, str]:
    if not name.strip() or not password:
        return None, "Enter a name and a password."
    with _conn() as connection:
        existing = connection.execute("SELECT id FROM users WHERE name = ?", (name.strip(),)).fetchone()
        if existing:
            return None, "That name is taken — try signing in instead."
        cursor = connection.execute(
            "INSERT INTO users (name, password_hash) VALUES (?, ?)",
            (name.strip(), hash_password(name.strip(), password)),
        )
        return cursor.lastrowid, ""


def login_user(name: str, password: str) -> tuple[int | None, str]:
    with _conn() as connection:
        row = connection.execute("SELECT id, password_hash FROM users WHERE name = ?", (name.strip(),)).fetchone()
    if not row:
        return None, "No account with that name — create one first."
    if row["password_hash"] != hash_password(name.strip(), password):
        return None, "Wrong password."
    return row["id"], ""


def create_movie_night(user_id: int | None, preferences: dict) -> int:
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
    with _conn() as connection:
        connection.execute(
            "INSERT INTO votes (night_id, movie_id, title, choice, voter) VALUES (?,?,?,?,?)",
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
