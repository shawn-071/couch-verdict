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
) -> tuple[list[MovieMatch], list[str]]:
    """Return up to five distinct matches, with notes about relaxed filters."""
    steps = [
        {
            "label": "Exact match", "pct": 97,
            "params": dict(genre_ids=genre_ids, genre_mode="and", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           min_year=min_year, language=language),
            "check_runtime": bool(max_runtime),
        },
        {
            "label": "Near match — any of your genres", "pct": 88,
            "params": dict(genre_ids=genre_ids, genre_mode="or", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime, cert_ceiling=cert_ceiling,
                           min_year=min_year, language=language),
            "check_runtime": bool(max_runtime),
        },
        {
            "label": "Near match — any length", "pct": 82,
            "params": dict(genre_ids=genre_ids, genre_mode="or", provider_ids=provider_ids,
                           region=region, max_runtime=None, cert_ceiling=cert_ceiling,
                           min_year=min_year, language=language),
            "check_runtime": False,
        },
        {
            "label": "Near match — top picks on your services", "pct": 74,
            "params": dict(genre_ids=None, provider_ids=provider_ids, region=region,
                           max_runtime=None, cert_ceiling=cert_ceiling,
                           min_year=min_year, language=language),
            "check_runtime": False,
        },
        {
            "label": "Near match — popular beyond your services", "pct": 66,
            "params": dict(genre_ids=None, provider_ids=None, region=region,
                           max_runtime=None, cert_ceiling=cert_ceiling,
                           min_year=min_year, language=language),
            "check_runtime": False,
        },
    ]
    matches: list[MovieMatch] = []
    seen: set[int] = set()
    used_steps: list[str] = []
    for step in steps:
        try:
            raw = tmdb_client.discover(pages=2, **step["params"])
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
            if step["check_runtime"] and max_runtime and runtime and runtime > max_runtime:
                continue
            cert = tmdb_client.us_certification(details)
            if not _cert_ok(cert, cert_ceiling):
                continue
            seen.add(movie_id)
            if step["label"] not in used_steps:
                used_steps.append(step["label"])
            providers = tmdb_client.flatrate_providers_for_region(details, region)
            year = (entry.get("release_date") or "")[:4]
            bonus = min(2, round(entry.get("vote_average", 0) / 10))
            matches.append(MovieMatch(
                movie_id=movie_id,
                title=entry.get("title", "Untitled"),
                year=year,
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
