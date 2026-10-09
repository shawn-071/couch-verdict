"""Unit tests for the always-5 relaxation engine, using fake TMDB data."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tmdb_client  # noqa: E402
from services import recommender  # noqa: E402

def fake_movie(mid, title, cert="PG-13", runtime=100, genres=(35, 12)):
    return {
        "id": mid,
        "title": title,
        "release_date": "2023-06-01",
        "poster_path": f"/{mid}.jpg",
        "genre_ids": list(genres),
        "vote_average": 7.2,
        "overview": f"Overview {title}",
    }

def fake_details(cert="PG-13", runtime=100, providers=("Netflix",)):
    return {
        "runtime": runtime,
        "release_dates": {
            "results": [
                {"iso_3166_1": "US",
                 "release_dates": [{"certification": cert}]}
            ]
        },
        "watch/providers": {"results": {"US": {"flatrate": [
            {"provider_name": p} for p in providers
        ]}}},
    }


class LadderTest(unittest.TestCase):
    def setUp(self):
        self._discover = tmdb_client.discover
        self._details = tmdb_client.movie_details
        self.details_map = {}
        tmdb_client.discover = self._fake_discover
        tmdb_client.movie_details = self._fake_details

    def tearDown(self):
        tmdb_client.discover = self._discover
        tmdb_client.movie_details = self._details

    def _fake_discover(self, **params):
        raise AssertionError("override _fake_discover")

    def _fake_details(self, movie_id):
        return self.details_map.get(movie_id, fake_details())

    def _run(self, pools, details_map=None):
        """pools: list of results per discover call (step order)."""
        self.pools = list(pools)
        if details_map is not None:
            self.details_map = details_map
        self.calls = []

        def discover(**params):
            self.calls.append(params)
            return self.pools.pop(0) if self.pools else []

        tmdb_client.discover = discover
        return recommender.find_five_movies(
            genre_ids=[35, 12],
            provider_ids=[8],
            region="US",
            max_runtime=120,
            cert_ceiling="PG-13",
        )

    def test_exact_matches_fill_five(self):
        pool = [fake_movie(i, f"Movie {i}") for i in range(1, 7)]
        matches, notes = self._run([pool])
        self.assertEqual(len(matches), 5)
        self.assertEqual(notes, ["Exact match"])
        self.assertTrue(all(m.match_label == "Exact match" for m in matches))
        self.assertEqual(len({m.movie_id for m in matches}), 5)  # distinct

    def test_relaxes_genres_when_sparse(self):
        exact = [fake_movie(1, "Only Exact")]
        broad = [fake_movie(i, f"Any Genre {i}") for i in range(2, 8)]
        matches, notes = self._run([exact, broad])
        self.assertEqual(len(matches), 5)
        self.assertIn("Near match — any of your genres", notes)
        self.assertEqual(matches[0].title, "Only Exact")

    def test_rated_movie_rejected_for_kids(self):
        pool = [
            fake_movie(1, "Kid Safe", cert="G"),
            fake_movie(2, "Adults Only", cert="R"),
            fake_movie(3, "Unknown Cert", cert=""),
        ]
        self.details_map = {
            1: fake_details(cert="G"),
            2: fake_details(cert="R"),
            3: fake_details(cert=""),
        }
        matches, _ = self._run([pool])
        ids = [m.movie_id for m in matches]
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)  # R is above PG-13 ceiling
        self.assertNotIn(3, ids)  # unverified rating is not age-safe

    def test_runtime_violation_skipped(self):
        pool = [
            fake_movie(1, "Too Long", runtime=180),
            fake_movie(2, "Fine"),
            fake_movie(3, "Fine"),
            fake_movie(4, "Fine"),
            fake_movie(5, "Fine"),
            fake_movie(6, "Fine"),
        ]
        self.details_map = {1: fake_details(runtime=180)}
        matches, _ = self._run([pool])
        titles = [m.title for m in matches]
        self.assertNotIn("Too Long", titles)
        self.assertEqual(len(matches), 5)

    def test_duplicates_deduped_across_steps(self):
        shared = [fake_movie(1, "Shared")]
        more = [fake_movie(i, f"Other {i}") for i in range(2, 7)]
        matches, _ = self._run([shared, shared + more])
        self.assertEqual([m.movie_id for m in matches].count(1), 1)

    def test_api_failure_returns_what_it_has(self):
        def discover(**params):
            raise tmdb_client.TMDBApiError("boom")

        tmdb_client.discover = discover
        matches, notes = recommender.find_five_movies(
            genre_ids=[35], provider_ids=[8], region="US",
            cert_ceiling="PG-13",
        )
        self.assertEqual(matches, [])
        self.assertEqual(notes, [])

    def test_fewer_than_five_when_nothing_safe(self):
        matches, _ = self._run([[fake_movie(1, "Lone Safe", cert="G")]])
        self.assertEqual(len(matches), 1)

    def test_age_ceiling_never_relaxed(self):
        """Even the last broad step keeps the cert ceiling param."""
        pool = [fake_movie(i, f"P {i}") for i in range(1, 8)]
        matches, notes = self._run([[], [], [], [], pool])
        self.assertEqual(len(matches), 5)
        last_params = self.calls[-1]
        self.assertEqual(last_params.get("cert_ceiling"), "PG-13")


if __name__ == "__main__":
    unittest.main(verbosity=2)
