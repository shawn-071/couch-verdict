"""TMDB API client. Calls are cached to reduce redundant API requests."""
from __future__ import annotations

import os
import requests
import streamlit as st

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
GENRE_CACHE_TTL = 86400
PROVIDER_CACHE_TTL = 86400
CONFIG_CACHE_TTL = 86400
DISCOVER_CACHE_TTL = 3600
DETAILS_CACHE_TTL = 86400


class TMDBConfigError(RuntimeError):
    """Raised when the TMDB API key is not configured."""


class TMDBApiError(RuntimeError):
    """Raised when TMDB returns an error response."""


def get_api_key() -> str:
    try:
        return st.secrets["tmdb"]["api_key"]
    except Exception:
        pass
    try:
        return st.secrets["TMDB_API_KEY"]
    except Exception:
        pass
    env_key = os.environ.get("TMDB_API_KEY")
    if env_key:
        return env_key
    raise TMDBConfigError(
        "TMDB API key is not configured. In Streamlit app settings → Secrets, add:\n\n"
        '[tmdb]\napi_key = "YOUR_KEY"'
    )


def _get(path: str, params: dict) -> dict:
    params = dict(params)
    params["api_key"] = get_api_key()
    try:
        response = requests.get(f"{BASE_URL}/{path}", params=params, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as exc:
        raise TMDBApiError(f"TMDB request failed ({path}): {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise TMDBApiError(f"Could not reach TMDB: {exc}") from exc


@st.cache_data(ttl=GENRE_CACHE_TTL, show_spinner=False)
def get_genres() -> dict[int, str]:
    data = _get("genre/movie/list", {"language": "en-US"})
    return {g["id"]: g["name"] for g in data.get("genres", [])}


@st.cache_data(ttl=PROVIDER_CACHE_TTL, show_spinner=False)
def get_providers(region: str = "US") -> dict[str, int]:
    data = _get("watch/providers/movie", {"watch_region": region, "language": "en-US"})
    return {p["provider_name"]: p["provider_id"] for p in data.get("results", [])}


@st.cache_data(ttl=CONFIG_CACHE_TTL, show_spinner=False)
def get_regions() -> dict[str, str]:
    """Return every country/region for which TMDB lists streaming providers."""
    data = _get("watch/providers/regions", {"language": "en-US"})
    results = data.get("results", [])
    return {
        str(item.get("english_name") or item.get("native_name") or item.get("iso_3166_1")): str(item["iso_3166_1"])
        for item in results
        if item.get("iso_3166_1")
    }


@st.cache_data(ttl=CONFIG_CACHE_TTL, show_spinner=False)
def get_languages() -> list[dict[str, str]]:
    """Return every ISO 639-1 language represented in TMDB's configuration."""
    data = _get("configuration/languages", {})
    results = []
    for item in data if isinstance(data, list) else []:
        code = str(item.get("iso_639_1") or "").strip()
        english_name = str(item.get("english_name") or item.get("name") or "").strip()
        if code and english_name:
            results.append({"code": code, "name": english_name})
    return sorted(results, key=lambda item: (item["name"].casefold(), item["code"]))


@st.cache_data(ttl=CONFIG_CACHE_TTL, show_spinner=False)
def get_movie_certifications() -> dict[str, list[dict[str, str]]]:
    """Return TMDB's official movie certification lists keyed by country code."""
    data = _get("certification/movie/list", {})
    raw = data.get("certifications", {})
    normalized: dict[str, list[dict[str, str]]] = {}
    if isinstance(raw, dict):
        for country, entries in raw.items():
            values = []
            for entry in entries or []:
                cert = str(entry.get("certification") or "").strip()
                if cert:
                    values.append({
                        "certification": cert,
                        "meaning": str(entry.get("meaning") or "").strip(),
                        "order": str(entry.get("order") or ""),
                    })
            values.sort(key=lambda item: (int(item["order"]) if item["order"].isdigit() else 999, item["certification"]))
            normalized[str(country)] = values
    return normalized


@st.cache_data(ttl=DISCOVER_CACHE_TTL, show_spinner=False)
def discover(
    genre_ids: list[int] | None = None,
    genre_mode: str = "and",
    provider_ids: list[int] | None = None,
    region: str = "US",
    max_runtime: int | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    language: str | None = None,
    pages: int = 2,
) -> list[dict]:
    params: dict = {
        "language": "en-US",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "vote_count.gte": 50,
    }
    if genre_ids:
        joiner = "," if genre_mode == "and" else "|"
        params["with_genres"] = joiner.join(str(g) for g in genre_ids)
    if provider_ids:
        params["with_watch_providers"] = "|".join(str(p) for p in provider_ids)
        params["watch_region"] = region
        params["with_watch_monetization_types"] = "flatrate"
    if max_runtime:
        params["with_runtime.lte"] = max_runtime
    if min_year:
        params["primary_release_date.gte"] = f"{min_year}-01-01"
    if max_year:
        params["primary_release_date.lte"] = f"{max_year}-12-31"
    if language:
        params["with_original_language"] = language
    results: list[dict] = []
    for page in range(1, pages + 1):
        try:
            data = _get("discover/movie", {**params, "page": page})
        except TMDBApiError:
            if page == 1:
                raise
            break
        results.extend(data.get("results", []))
        if page >= data.get("total_pages", 1):
            break
    return results


@st.cache_data(ttl=DETAILS_CACHE_TTL, show_spinner=False)
def movie_details(movie_id: int) -> dict:
    return _get(
        f"movie/{movie_id}",
        {"language": "en-US", "append_to_response": "release_dates,watch/providers"},
    )


def poster_url(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return f"{IMAGE_BASE}{poster_path}"


def certification_for_region(details: dict, region: str) -> str | None:
    """Return the first non-empty movie certification recorded for the selected region."""
    for entry in details.get("release_dates", {}).get("results", []):
        if entry.get("iso_3166_1") == region:
            release_dates = sorted(
                entry.get("release_dates", []),
                key=lambda item: (item.get("release_date") or "9999", item.get("type") or 99),
            )
            for release in release_dates:
                cert = str(release.get("certification") or "").strip()
                if cert:
                    return cert
            break
    return None


def us_certification(details: dict) -> str | None:
    """Backward-compatible helper for the old US-only rating display."""
    return certification_for_region(details, "US")


def flatrate_providers_for_region(details: dict, region: str) -> list[str]:
    providers = details.get("watch/providers", {}).get("results", {})
    entry = providers.get(region, {})
    return [p.get("provider_name") for p in entry.get("flatrate", [])]
