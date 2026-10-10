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


def fake_details(cert="PG-13", runtime=100, provider_ids=(8,)):
    return {
        "runtime": runtime,
        "release_dates": {
            "results": [
                {"iso_3166_1": "US",
                 "release_dates": [{"certification": cert}]}
            ]
        },
        "watch/providers": {"results": {"US": {"flatrate": [
            {"provider_id": p} for p in provider_ids
        ]}}},
    }


class LadderTest(unittest.TestCase):
    def setUp(self):
        self._discover = tmdb_client.discover
        self._details = tmdb_client.movie_details
        self._providers = tmdb_client.get_providers
        self.details_map = {}
        tmdb_client.discover = self._fake_discover
        tmdb_client.movie_details = self._fake_details
        tmdb_client.get_providers = lambda region: {"Netflix": 8, "Max": 1899}

    def tearDown(self):
        tmdb_client.discover = self._discover
        tmdb_client.movie_details = self._details
        tmdb_client.get_providers = self._providers

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
        matches, notes, error = self._run([pool])
        self.assertEqual(len(matches), 5)
        self.assertEqual(notes, ["Exact match"])
        self.assertTrue(all(m.match_label == "Exact match" for m in matches))
        self.assertEqual(len({m.movie_id for m in matches}), 5)  # distinct
        self.assertIsNone(error)

    def test_relaxes_genres_when_sparse(self):
        exact = [fake_movie(1, "Only Exact")]
        broad = [fake_movie(i, f"Any Genre {i}") for i in range(2, 8)]
        matches, notes, error = self._run([exact, broad])
        self.assertEqual(len(matches), 5)
        self.assertIn("Near match — any of your genres", notes)
        self.assertEqual(matches[0].title, "Only Exact")
        self.assertIsNone(error)

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
        matches, _, _ = self._run([pool])
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
        matches, _, _ = self._run([pool])
        titles = [m.title for m in matches]
        self.assertNotIn("Too Long", titles)
        self.assertEqual(len(matches), 5)

    def test_unverified_runtime_rejected_in_capped_step(self):
        """Missing/zero runtime must fail the capped check, not pass it."""
        pool = [
            fake_movie(1, "No Runtime Data", runtime=None),
            fake_movie(2, "Fine"),
            fake_movie(3, "Fine"),
            fake_movie(4, "Fine"),
            fake_movie(5, "Fine"),
            fake_movie(6, "Fine"),
        ]
        self.details_map = {1: fake_details(runtime=None)}
        matches, _, _ = self._run([pool])
        titles = [m.title for m in matches]
        self.assertNotIn("No Runtime Data", titles)
        self.assertEqual(len(matches), 5)

    def test_provider_mismatch_skipped(self):
        """Movie not on a selected subscription is skipped in constrained steps."""
        pool = [fake_movie(1, "Wrong Service")]
        self.details_map = {1: fake_details(provider_ids=(999,))}
        matches, notes, _ = self._run([pool, [], [], [], []])
        self.assertEqual(matches, [])  # never accepted as an exact match

    def test_duplicates_deduped_across_steps(self):
        shared = [fake_movie(1, "Shared")]
        more = [fake_movie(i, f"Other {i}") for i in range(2, 7)]
        matches, _, _ = self._run([shared, shared + more])
        self.assertEqual([m.movie_id for m in matches].count(1), 1)

    def test_api_failure_reported_not_swallowed(self):
        def discover(**params):
            raise tmdb_client.TMDBApiError("boom")

        tmdb_client.discover = discover
        matches, notes, error = recommender.find_five_movies(
            genre_ids=[35], provider_ids=[8], region="US",
            cert_ceiling="PG-13",
        )
        self.assertEqual(matches, [])
        self.assertEqual(notes, [])
        self.assertEqual(error, "boom")

    def test_partial_failure_reports_error_with_results(self):
        """If TMDB dies mid-search, keep verified results AND surface the error."""
        call_state = {"n": 0}

        def discover(**params):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return [fake_movie(1, "Verified Early")]
            raise tmdb_client.TMDBApiError("HTTP 500")

        tmdb_client.discover = discover
        matches, notes, error = recommender.find_five_movies(
            genre_ids=[35, 12], provider_ids=[8], region="US",
            max_runtime=120, cert_ceiling="PG-13",
        )
        self.assertEqual(len(matches), 1)
        self.assertIsNotNone(error)
        self.assertIn("500", error)

    def test_fewer_than_five_when_nothing_safe(self):
        matches, notes, error = self._run([[fake_movie(1, "Lone Safe", cert="G")]])
        self.assertEqual(len(matches), 1)
        self.assertIsNone(error)

    def test_age_ceiling_never_relaxed(self):
        """Even the last broad step keeps the cert ceiling param."""
        pool = [fake_movie(i, f"P {i}") for i in range(1, 8)]
        matches, notes, _ = self._run([[], [], [], [], pool])
        self.assertEqual(len(matches), 5)
        last_params = self.calls[-1]
        self.assertEqual(last_params.get("cert_ceiling"), "PG-13")

    def test_labels_accumulate_relaxations(self):
        pool = [fake_movie(i, f"P {i}") for i in range(1, 8)]
        matches, notes, _ = self._run([[], [], [], pool])
        self.assertIn("Near match — any genre, any length, top picks on your services",
                      notes)
        labels = {m.match_label for m in matches}
        self.assertIn("Near match — any genre, any length, top picks on your services",
                      labels)


    def test_adults_only_rejects_pg13(self):
        """Regression: 'Adults only' must never return PG-13 movies."""
        pool = [
            fake_movie(1, "Family Film", cert="PG-13"),
            fake_movie(2, "Adult Film", cert="R"),
            fake_movie(3, "Kid Film", cert="G"),
            fake_movie(4, "Adult Film 2", cert="NC-17"),
        ]
        self.details_map = {
            1: fake_details(cert="PG-13"),
            2: fake_details(cert="R"),
            3: fake_details(cert="G"),
            4: fake_details(cert="NC-17"),
        }
        # simulate adults-only: ceiling=None, floor="R"
        def discover(**params):
            return pool
        tmdb_client.discover = discover
        matches, notes, error = recommender.find_five_movies(
            genre_ids=[35], provider_ids=[8], region="US",
            cert_ceiling=None, cert_floor="R",
        )
        certs = [m.certification for m in matches]
        self.assertEqual(certs, ["R", "NC-17"])  # only mature films
        self.assertNotIn("PG-13", certs)
        self.assertNotIn("G", certs)

    def test_year_bounds_filter_client_side(self):
        """Typed years are enforced client-side, unknown year rejected."""
        from pathlib import Path as _P
        pool = [
            dict(fake_movie(1, "Old"), release_date="1994-05-05"),
            dict(fake_movie(2, "In Range"), release_date="1998-05-05"),
            dict(fake_movie(3, "New"), release_date="2005-05-05"),
            dict(fake_movie(4, "No Date"), release_date=""),
        ]
        def discover(**params):
            return pool
        tmdb_client.discover = discover
        matches, notes, error = recommender.find_five_movies(
            genre_ids=[35], provider_ids=[8], region="US",
            cert_ceiling=None, min_year=1995, max_year=2000,
        )
        titles = [m.title for m in matches]
        self.assertIn("In Range", titles)
        self.assertNotIn("Old", titles)
        self.assertNotIn("New", titles)
        self.assertNotIn("No Date", titles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
