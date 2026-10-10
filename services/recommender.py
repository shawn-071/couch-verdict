"""Couch Verdict V.5.0 recommendation engine with region-specific rating filters."""
from __future__ import annotations

from dataclasses import dataclass, field
from services import tmdb_client

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


def find_five_movies(
    genre_ids: list[int],
    provider_ids: list[int],
    region: str = "US",
    max_runtime: int | None = None,
    allowed_certifications: list[str] | None = None,
    min_year: int | None = None,
    language: str | None = None,
    release_decades: list[int] | None = None,
) -> tuple[list[MovieMatch], list[str]]:
    """Return up to five matches while keeping time and rating filters strict.

    ``release_decades`` contains decade start years (for example ``[1980, 2020]``).
    Genre and provider preferences may be broadened during fallback searches, but
    a selected runtime ceiling, release decade, language, and regional certification
    must remain satisfied. Specific rating selections require a known certificate
    for the requested region; ``None`` means the user chose Any rating.
    """
    from datetime import date

    steps = [
        {
            "label": "Exact match", "pct": 97,
            "params": dict(genre_ids=genre_ids, genre_mode="and", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime,
                           language=language),
        },
        {
            "label": "Near match — any of your genres", "pct": 88,
            "params": dict(genre_ids=genre_ids, genre_mode="or", provider_ids=provider_ids,
                           region=region, max_runtime=max_runtime,
                           language=language),
        },
        {
            "label": "Near match — top picks on your services", "pct": 74,
            "params": dict(genre_ids=None, provider_ids=provider_ids, region=region,
                           max_runtime=max_runtime,
                           language=language),
        },
        {
            "label": "Near match — popular beyond your services", "pct": 66,
            "params": dict(genre_ids=None, provider_ids=None, region=region,
                           max_runtime=max_runtime,
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
            # Certifications differ by country. When specific ratings were chosen,
            # require a known certification for this region and an exact selection match.
            cert = tmdb_client.certification_for_region(details, region)
            if allowed_certifications and cert not in allowed_certifications:
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
