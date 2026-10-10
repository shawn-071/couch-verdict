"""Recommendation engine: tries hard to return 5 distinct movies.

Relaxation ladder (the age ceiling is NEVER relaxed):
1. Exact match: all chosen genres, chosen services, runtime cap, age cap.
2. Any of the chosen genres.
3. Any runtime (genre + services + age cap kept).
4. Top picks on the chosen services (age cap kept).
5. Popular movies regardless of service (age cap kept).

Each result carries a label describing everything that was relaxed, so the UI
can be honest about near-matches. If TMDB fails or cannot supply five
age-suitable movies, fewer (or zero) are returned and an error/report is
surfaced to the caller — the app never invents films.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services import tmdb_client

# US rating severity ranking (G is safest).
_CERT_RANK = {
    "G": 0, "TV-G": 0, "TV-Y": 0, "TV-Y7": 1,
    "PG": 1, "TV-PG": 1,
    "PG-13": 2, "TV-14": 2,
    "R": 3, "TV-MA": 3,
    "NC-17": 4,
}

# Age rules per audience: (minimum rating, maximum rating), US ratings.
# Adults-only means mature content: R / NC-17 (TV-MA). Neither bound is ever
# relaxed by the fallback ladder.
AUDIENCE_RATING_RANGE = {
    "kids": (None, "PG"),
    "mixed": (None, "PG-13"),
    "adults": ("R", None),
}
AUDIENCE_CERT_CEILING = {k: v[1] for k, v in AUDIENCE_RATING_RANGE.items()}
AUDIENCE_CERT_FLOOR = {k: v[0] for k, v in AUDIENCE_RATING_RANGE.items()}

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


def _cert_ok(
    cert: str | None, ceiling: str | None, floor: str | None = None
) -> bool:
    """Client-side age check against a rating range.

    Unknown or unrecognised ratings are never treated as matching when any
    bound is set.
    """
    if ceiling is None and floor is None:
        return True
    if cert is None:
        return False
    rank = _CERT_RANK.get(cert.upper().replace(" ", "-"))
    if rank is None:
        return False
    if ceiling is not None:
        ceiling_rank = _CERT_RANK.get(ceiling.upper())
        if ceiling_rank is None or rank > ceiling_rank:
            return False
    if floor is not None:
        floor_rank = _CERT_RANK.get(floor.upper())
        if floor_rank is None or rank < floor_rank:
            return False
    return True


def _year_ok(release_date: str | None, min_year: int | None,
             max_year: int | None) -> bool:
    """Client-side release-year check. Unknown year fails when a bound is set."""
    if min_year is None and max_year is None:
        return True
    try:
        year = int((release_date or "")[:4])
    except ValueError:
        return False
    if min_year is not None and year < min_year:
        return False
    if max_year is not None and year > max_year:
        return False
    return True


def find_five_movies(
    genre_ids: list[int],
    provider_ids: list[int],
    region: str = "US",
    max_runtime: int | None = None,
    cert_ceiling: str | None = None,
    min_year: int | None = None,
    language: str | None = None,
    cert_floor: str | None = None,
    max_year: int | None = None,
) -> tuple[list[MovieMatch], list[str], str | None]:
    """Return (matches, relaxation_steps_used, error).

    matches holds up to 5 distinct, verified movies. error is None on a
    healthy TMDB round trip; otherwise it carries the sanitized API error.
    """
    steps = [
        {
            "label": "Exact match",
            "pct": 97,
            "params": dict(genre_ids=genre_ids, genre_mode="and",
                          provider_ids=provider_ids, region=region,
                          max_runtime=max_runtime, cert_ceiling=cert_ceiling, cert_floor=cert_floor,
                          min_year=min_year, max_year=max_year, language=language),
            "check_runtime": bool(max_runtime),
            "check_providers": True,
        },
        {
            "label": "Near match — any of your genres",
            "pct": 88,
            "params": dict(genre_ids=genre_ids, genre_mode="or",
                          provider_ids=provider_ids, region=region,
                          max_runtime=max_runtime, cert_ceiling=cert_ceiling, cert_floor=cert_floor,
                          min_year=min_year, max_year=max_year, language=language),
            "check_runtime": bool(max_runtime),
            "check_providers": True,
        },
        {
            "label": "Near match — any genre, any length",
            "pct": 82,
            "params": dict(genre_ids=genre_ids, genre_mode="or",
                          provider_ids=provider_ids, region=region,
                          max_runtime=None, cert_ceiling=cert_ceiling, cert_floor=cert_floor,
                          min_year=min_year, max_year=max_year, language=language),
            "check_runtime": False,
            "check_providers": True,
        },
        {
            "label": "Near match — any genre, any length, top picks on your services",
            "pct": 74,
            "params": dict(genre_ids=None, provider_ids=provider_ids,
                          region=region, max_runtime=None,
                          cert_ceiling=cert_ceiling, min_year=min_year,
                          language=language),
            "check_runtime": False,
            "check_providers": True,
        },
        {
            "label": "Near match — popular beyond your services",
            "pct": 66,
            "params": dict(genre_ids=None, provider_ids=None, region=region,
                          max_runtime=None, cert_ceiling=cert_ceiling, cert_floor=cert_floor,
                          min_year=min_year, max_year=max_year, language=language),
            "check_runtime": False,
            "check_providers": False,
        },
    ]

    matches: list[MovieMatch] = []
    seen: set[int] = set()
    used_steps: list[str] = []
    api_error: str | None = None

    try:
        provider_names = {pid: name for name, pid in
                          tmdb_client.get_providers(region).items()}
    except Exception as exc:
        return [], [], f"Could not load streaming services: {exc}"

    selected_ids = set(provider_ids)

    for step in steps:
        if len(matches) >= TARGET:
            break
        try:
            raw = tmdb_client.discover(pages=2, **step["params"])
        except Exception as exc:
            api_error = str(exc)
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
                continue  # skip movies whose details can't be verified

            runtime = details.get("runtime")
            if step["check_runtime"] and max_runtime:
                # Unverified (missing/zero) runtime fails the capped check.
                if not runtime or runtime > max_runtime:
                    continue

            cert = tmdb_client.us_certification(details)
            if not _cert_ok(cert, cert_ceiling, cert_floor):
                continue

            if not _year_ok(
                entry.get("release_date"), min_year, max_year
            ):
                continue

            flatrate_ids = set(
                tmdb_client.flatrate_provider_ids_for_region(details, region)
            )
            if step["check_providers"] and selected_ids:
                if not (flatrate_ids & selected_ids):
                    continue  # not actually on a chosen subscription

            seen.add(movie_id)
            if step["label"] not in used_steps:
                used_steps.append(step["label"])

            provider_display = [
                provider_names[pid] for pid in flatrate_ids
                if pid in provider_names
            ]
            year = (entry.get("release_date") or "")[:4]
            # Small popularity bonus within each relaxation step.
            bonus = min(2, round(entry.get("vote_average", 0) / 10))
            matches.append(
                MovieMatch(
                    movie_id=movie_id,
                    title=entry.get("title", "Untitled"),
                    year=year,
                    poster_path=entry.get("poster_path"),
                    runtime=runtime,
                    certification=cert,
                    genre_ids=entry.get("genre_ids", []),
                    vote_average=entry.get("vote_average", 0.0),
                    overview=entry.get("overview", ""),
                    providers=provider_display,
                    match_label=step["label"],
                    match_pct=step["pct"] + bonus,
                )
            )

    return matches, used_steps, api_error
