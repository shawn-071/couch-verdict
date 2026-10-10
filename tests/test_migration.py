"""Tests for upgrading an old database (old votes schema + legacy passwords)."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import db  # noqa: E402

DB = Path(db.DB_PATH)


class MigrationTest(unittest.TestCase):
    def setUp(self):
        if DB.exists():
            DB.unlink()

    def tearDown(self):
        if DB.exists():
            DB.unlink()

    def _create_old_db(self):
        """Schema and password format of the previously deployed version."""
        conn = sqlite3.connect(DB)
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE movie_nights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                preferences TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                night_id INTEGER,
                movie_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                choice TEXT NOT NULL,
                voter TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        import hashlib
        legacy_hash = hashlib.sha256(b"couch::shawn::oldpw").hexdigest()
        conn.execute(
            "INSERT INTO users (name, password_hash) VALUES ('shawn', ?)",
            (legacy_hash,),
        )
        conn.execute(
            "INSERT INTO votes (night_id, movie_id, title, choice, voter) VALUES "
            "(1, 550, 'Old Movie', 'Watch this', 'shawn')"
        )
        conn.commit()
        conn.close()

    def test_votes_unique_constraint_added(self):
        self._create_old_db()
        db.init_db()
        # the new ON CONFLICT upsert must work on the migrated table
        db.record_vote(1, 550, "Old Movie", "Maybe", "shawn")
        with sqlite3.connect(DB) as conn:
            rows = conn.execute(
                "SELECT choice FROM votes WHERE movie_id = 550"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Maybe")

    def test_legacy_password_upgrades(self):
        self._create_old_db()
        db.init_db()
        # wrong password rejected
        uid, err = db.login_user("shawn", "WRONG")
        self.assertIsNone(uid)
        # correct legacy password accepted and upgraded to PBKDF2
        uid, err = db.login_user("shawn", "oldpw")
        self.assertIsNotNone(uid)
        with sqlite3.connect(DB) as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE name='shawn'"
            ).fetchone()[0]
        self.assertTrue(stored.startswith("pbkdf2$"))
        # re-login with the same password now uses the new hash
        uid2, err2 = db.login_user("shawn", "oldpw")
        self.assertIsNotNone(uid2)
        self.assertEqual(uid, uid2)

    def test_fresh_db_untouched(self):
        db.init_db()
        db.register_user("fresh", "pw123")
        uid, err = db.login_user("fresh", "pw123")
        self.assertIsNotNone(uid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
