"""End-to-end AppTest flows: registration, search, voting, verdicts."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

from streamlit.testing.v1 import AppTest  # noqa: E402

from services import tmdb_client  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DB_FILE = Path(__file__).resolve().parent.parent / "couch_verdict.db"

FAKE_GENRES = {35: "Comedy", 12: "Adventure", 16: "Animation", 10751: "Family"}
FAKE_PROVIDERS = {"Netflix": 8, "Prime Video": 9, "Max": 1899, "Hulu": 15}
FAKE_REGION = "US"


def fake_movie(mid, title):
    return {
        "id": mid,
        "title": title,
        "release_date": "2023-06-01",
        "poster_path": f"/{mid}.jpg",
        "genre_ids": [35, 12],
        "vote_average": 7.2,
        "overview": f"Overview {title}",
    }


def fake_details(mid):
    return {
        "runtime": 100,
        "release_dates": {"results": [
            {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]}
        ]},
        "watch/providers": {"results": {"US": {"flatrate": [
            {"provider_id": 8, "provider_name": "Netflix"}
        ]}}},
    }


FAKE_LANGS = {
    "ar": "Arabic", "zh": "Chinese", "en": "English", "fr": "French",
    "ko": "Korean", "es": "Spanish", "tr": "Turkish",
}


def install_mocks(pool):
    tmdb_client.get_genres = lambda: FAKE_GENRES
    tmdb_client.get_providers = lambda region: FAKE_PROVIDERS
    tmdb_client.get_languages = lambda: FAKE_LANGS
    tmdb_client.discover = lambda **params: pool
    tmdb_client.movie_details = fake_details


def click(at, label):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button labeled {label!r}"
    matches[0].click()


class AppFlowTest(unittest.TestCase):
    def setUp(self):
        if DB_FILE.exists():
            DB_FILE.unlink()
        install_mocks([fake_movie(i, f"Movie {i}") for i in range(1, 9)])

    def tearDown(self):
        if DB_FILE.exists():
            DB_FILE.unlink()

    def test_register_via_form(self):
        at = AppTest.from_file(APP)
        at.run()
        assert not at.exception
        at.text_input(key="login_name").set_value("Shawn")
        at.text_input(key="login_password").set_value("secret123")
        click(at, "Create account")
        at.run()
        assert not at.exception
        self.assertEqual(at.session_state["user"]["name"], "Shawn")

    def test_sign_in_wrong_password(self):
        at = AppTest.from_file(APP)
        at.run()
        at.text_input(key="login_name").set_value("Shawn")
        at.text_input(key="login_password").set_value("secret123")
        click(at, "Create account")
        at.run()

        at2 = AppTest.from_file(APP)
        at2.run()
        at2.text_input(key="login_name").set_value("Shawn")
        at2.text_input(key="login_password").set_value("WRONG")
        click(at2, "Sign in")
        at2.run()
        assert not at2.exception
        self.assertIsNone(at2.session_state["user"])

    def test_full_flow_search_returns_five(self):
        at = AppTest.from_file(APP)
        at.run()
        at.session_state["page"] = "preferences"
        at.session_state["user"] = {"id": 1, "name": "Shawn"}
        at.run()
        assert not at.exception

        # Services default to popular; pick genres on the second multiselect.
        at.multiselect[1].set_value(["Comedy"])
        click(at, "Find our 5 movies")
        at.run()
        assert not at.exception, at.exception
        self.assertEqual(at.session_state["page"], "results")
        self.assertEqual(len(at.session_state["results"]), 5)
        self.assertEqual(at.session_state["relax_notes"], ["Exact match"])

    def test_duplicate_ballots_replaced_not_accumulated(self):
        at = AppTest.from_file(APP)
        at.run()
        for k, v in {
            "page": "vote", "user": {"id": 1, "name": "Shawn"},
            "results": None, "relax_notes": ["Exact match"], "night_id": 1,
        }.items():
            at.session_state[k] = v
        from services.recommender import MovieMatch
        at.session_state["results"] = [
            MovieMatch(1, "A", "2020", None, 100, "PG-13", [35], 7.0, "x",
                       ["Netflix"], "Exact match", 97),
            MovieMatch(2, "B", "2021", None, 100, "PG-13", [35], 7.0, "x",
                       ["Netflix"], "Exact match", 97),
        ]
        at.run()
        assert not at.exception
        at.text_input(key="voter_name").set_value("Ali")
        at.run()

        click(at, "Watch this")   # movie 1, Ali
        at.run()
        click(at, "Watch this")   # movie 1, Ali again — replaces ballot
        at.run()
        ballots = at.session_state["ballots"]
        self.assertEqual(len(ballots), 1)
        self.assertEqual(list(ballots.values()), ["Watch this"])

    def test_verdict_requires_votes(self):
        at = AppTest.from_file(APP)
        at.run()
        from services.recommender import MovieMatch
        for k, v in {
            "page": "vote", "user": {"id": 1, "name": "Shawn"},
            "results": [MovieMatch(1, "A", "2020", None, 100, "PG-13", [35],
                                   7.0, "x", ["Netflix"], "Exact match", 97)],
            "relax_notes": ["Exact match"], "night_id": 1,
        }.items():
            at.session_state[k] = v
        at.run()
        click(at, "Show the verdict")
        at.run()
        assert not at.exception
        self.assertIsNone(at.session_state["verdict"])  # no invented winner

    def test_all_pass_yields_no_winner(self):
        at = AppTest.from_file(APP)
        at.run()
        from services.recommender import MovieMatch
        for k, v in {
            "page": "vote", "user": {"id": 1, "name": "Shawn"},
            "results": [MovieMatch(1, "A", "2020", None, 100, "PG-13", [35],
                                   7.0, "x", ["Netflix"], "Exact match", 97)],
            "relax_notes": ["Exact match"], "night_id": 1,
        }.items():
            at.session_state[k] = v
        at.run()
        at.text_input(key="voter_name").set_value("Ali")
        at.run()
        click(at, "Pass")
        at.run()
        click(at, "Show the verdict")
        at.run()
        self.assertEqual(at.session_state["verdict"], "none")
        self.assertIn("No winner", "\n".join(str(m) for m in at.markdown) +
                      str(at.header[0].value if at.header else ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
