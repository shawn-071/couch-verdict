"""Recommendation engine: return up to five distinct movies, preserving the age ceiling."""
from __future__ import annotations

from dataclasses import dataclass, field
from services import tmdb_client

_CERT_RANK = {
    "G": 0, "TV-G": 0, "TV-Y": 0, "TV-Y7": 1,
    "PG": 1, "TV-PG": 1,
    "PG-13": 2, "TV-14": 2,
    "R": 3, "TV-MA": 3,
    "NC-17": 4,
}
AUDIENCE_CERT_CEILING = {"kids": "PG", "mixed": "PG-13", "adults": None}
TARGET = 5


@dataclass
class MovieMatch:
    movie_id: int
    title: str
    year: str
    poster_path: str | None
    runtime: int | None
    certification: str | None
    genre_ids: list[int]
    vote_average: float
    overview: str
    providers: list[str] = field(default_factory=list)
    match_label: str = "Exact match"
    match_pct: int = 100

    @property
    def runtime_text(self) -> str:
        if not self.runtime:
            return "Runtime unknown"
        hours, minutes = divmod(self.runtime, 60)
        if hours:
            return f"{hours}h {minutes}m" if minutes else f"{hours}h"
        return f"{minutes}m"


def _cert_ok(cert: str | None, ceiling: str | None) -> bool:
    """Unknown ratings are not treated as age-safe when an age ceiling is set."""
    if ceiling is None:
        return True
    if cert is None:
        return False
    rank = _CERT_RANK.get(cert.upper().replace(" ", "-"))
    ceiling_rank = _CERT_RANK.get(ceiling.upper())
    return rank is not None and ceiling_rank is not None and rank <= ceiling_rank


def find_five_movies(
    genre_ids: list[int],
    provider_ids: list[int],
    region: str = "US",
    max_runtime: int | None = None,
    cert_ceiling: str | None = None,
    min_year: int | None = None,
    language: str | None = None,
    release_decades: list[int] | None = None,
) -> tuple[list[MovieMatch], list[str]]:
    """Return up to five matches. Runtime and selected release decades stay strict.

    Genre and provider preferences may be broadened to find alternatives, but a
    requested runtime ceiling is never relaxed. Movies with an unknown runtime
    are excluded when a ceiling is active.
    """
    from datetime import date

    steps = [
        {
            "label": "Exact match", "pct": 97,
            "params": dict(genre_ids=genre_ids, genre_mode="and", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           language=language),
        },
        {
            "label": "Near match — any of your genres", "pct": 88,
            "params": dict(genre_ids=genre_ids, genre_mode="or", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           language=language),
        },
        {
            "label": "Near match — top picks on your services", "pct": 74,
            "params": dict(genre_ids=None, provider_ids=provider_ids, region=region,
                           max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           language=language),
        },
        {
            "label": "Near match — popular beyond your services", "pct": 66,
            "params": dict(genre_ids=None, provider_ids=None, region=region,
                           max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           language=language),
        },
    ]

    decades = sorted(set(int(decade) for decade in (release_decades or []) if int(decade) >= 1800))

    def fetch_candidates(params: dict) -> list[dict]:
        # Query each selected decade separately so a selection like 1980s + 2020s
        # never accidentally includes movies from the 1990s, 2000s, or 2010s.
        if not decades:
            return tmdb_client.discover(min_year=min_year, pages=2, **params)
        combined: dict[int, dict] = {}
        current_year = date.today().year
        for decade in decades:
            year_end = min(decade + 9, current_year)
            if decade > year_end:
                continue
            raw_for_decade = tmdb_client.discover(
                min_year=decade, max_year=year_end, pages=2, **params
            )
            for item in raw_for_decade:
                movie_id = item.get("id")
                if movie_id:
                    combined[movie_id] = item
        return sorted(
            combined.values(),
            key=lambda item: float(item.get("popularity") or 0),
            reverse=True,
        )

    matches: list[MovieMatch] = []
    seen: set[int] = set()
    used_steps: list[str] = []
    for step in steps:
        try:
            raw = fetch_candidates(step["params"])
        except tmdb_client.TMDBApiError:
            break
        for entry in raw:
            if len(matches) >= TARGET:
                break
            movie_id = entry.get("id")
            if not movie_id or movie_id in seen:
                continue
            try:
                details = tmdb_client.movie_details(movie_id)
            except Exception:
                continue
            runtime = details.get("runtime")
            if max_runtime and (not runtime or runtime > max_runtime):
                continue
            # Extra client-side checks guard against incomplete or inconsistent API data.
            release_date = (entry.get("release_date") or "")
            if decades:
                try:
                    release_year = int(release_date[:4])
                except (TypeError, ValueError):
                    continue
                if not any(decade <= release_year <= min(decade + 9, date.today().year) for decade in decades):
                    continue
            if min_year and not decades:
                try:
                    if int(release_date[:4]) < min_year:
                        continue
                except (TypeError, ValueError):
                    continue
            cert = tmdb_client.us_certification(details)
            if not _cert_ok(cert, cert_ceiling):
                continue
            seen.add(movie_id)
            if step["label"] not in used_steps:
                used_steps.append(step["label"])
            providers = tmdb_client.flatrate_providers_for_region(details, region)
            bonus = min(2, round(entry.get("vote_average", 0) / 10))
            matches.append(MovieMatch(
                movie_id=movie_id,
                title=entry.get("title", "Untitled"),
                year=release_date[:4],
                poster_path=entry.get("poster_path"),
                runtime=runtime,
                certification=cert,
                genre_ids=entry.get("genre_ids", []),
                vote_average=entry.get("vote_average", 0.0),
                overview=entry.get("overview", ""),
                providers=providers,
                match_label=step["label"],
                match_pct=step["pct"] + bonus,
            ))
        if len(matches) >= TARGET:
            break
    return matches, used_steps
