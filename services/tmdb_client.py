"""TMDB API client for Couch Verdict.

All calls are cached with st.cache_data so a movie night with several
filter steps does not burn through API rate limits.
"""

from __future__ import annotations

import requests
import streamlit as st

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

GENRE_CACHE_TTL = 86400
PROVIDER_CACHE_TTL = 86400
DISCOVER_CACHE_TTL = 3600
DETAILS_CACHE_TTL = 86400


class TMDBConfigError(RuntimeError):
    """Raised when the TMDB API key is not configured in Streamlit secrets."""


class TMDBApiError(RuntimeError):
    """Raised when TMDB returns an error response."""


def get_api_key() -> str:
    """Read the TMDB key from Streamlit secrets (locally or on Community Cloud).

    Supports both formats so the app works no matter how the secret was pasted:
      [tmdb] / api_key = "..."          (section style)
      TMDB_API_KEY = "..."             (flat style)
    Falls back to the TMDB_API_KEY environment variable.
    """
    try:
        return st.secrets["tmdb"]["api_key"]
    except Exception:
        pass
    try:
        return st.secrets["TMDB_API_KEY"]
    except Exception:
        pass
    import os

    env_key = os.environ.get("TMDB_API_KEY")
    if env_key:
        return env_key
    raise TMDBConfigError(
        "TMDB API key is not configured. On Streamlit Community Cloud go to "
        "your app's Settings > Secrets and add:\n\n"
        '[tmdb]\napi_key = "YOUR_KEY"'
    )


def _get(path: str, params: dict) -> dict:
    try:
        api_key = get_api_key()
    except TMDBConfigError:
        raise
    params = dict(params)
    params["api_key"] = api_key
    try:
        response = requests.get(f"{BASE_URL}/{path}", params=params, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError:
        # Never include the exception text or URL: both would expose the API key.
        raise TMDBApiError(
            f"TMDB request failed ({path}): HTTP {response.status_code}"
        )
    except requests.exceptions.RequestException:
        raise TMDBApiError(f"Could not reach TMDB ({path})")


@st.cache_data(ttl=GENRE_CACHE_TTL, show_spinner=False)
def get_genres() -> dict[int, str]:
    """Map of TMDB genre id -> genre name."""
    data = _get("genre/movie/list", {"language": "en-US"})
    return {g["id"]: g["name"] for g in data.get("genres", [])}


@st.cache_data(ttl=PROVIDER_CACHE_TTL, show_spinner=False)
def get_providers(region: str = "US") -> dict[str, int]:
    """Map of streaming provider name -> TMDB provider id for a region."""
    data = _get("watch/providers/movie", {"watch_region": region, "language": "en-US"})
    return {p["provider_name"]: p["provider_id"] for p in data.get("results", [])}


@st.cache_data(ttl=DISCOVER_CACHE_TTL, show_spinner=False)
def discover(
    genre_ids: list[int] | None = None,
    genre_mode: str = "and",  # "and" = must have all, "or" = any of them
    provider_ids: list[int] | None = None,
    region: str = "US",
    max_runtime: int | None = None,
    cert_ceiling: str | None = None,
    min_year: int | None = None,
    language: str | None = None,
    pages: int = 2,
    cert_floor: str | None = None,
    max_year: int | None = None,
) -> list[dict]:
    """Search TMDB discover endpoint. Returns raw movie dicts."""
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
    if cert_ceiling or cert_floor:
        # US-style age ratings. Streaming region stays separate.
        params["certification_country"] = "US"
        if cert_ceiling:
            params["certification.lte"] = cert_ceiling
        if cert_floor:
            params["certification.gte"] = cert_floor
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
    """Movie details incl. runtime, US certification and watch providers."""
    return _get(
        f"movie/{movie_id}",
        {"language": "en-US", "append_to_response": "release_dates,watch/providers"},
    )


def poster_url(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return f"{IMAGE_BASE}{poster_path}"


def us_certification(details: dict) -> str | None:
    """Best known US theatrical certification (e.g. 'PG-13'), or None."""
    for entry in details.get("release_dates", {}).get("results", []):
        if entry.get("iso_3166_1") == "US":
            certs = [rd.get("certification") for rd in entry.get("release_dates", [])]
            certs = [c for c in certs if c]
            if certs:
                return certs[0]
    return None


def flatrate_provider_ids_for_region(details: dict, region: str) -> list[int]:
    """Provider IDs that stream this movie on subscription in a region."""
    providers = details.get("watch/providers", {}).get("results", {})
    entry = providers.get(region, {})
    return [p.get("provider_id") for p in entry.get("flatrate", []) if p.get("provider_id")]


# Fallback used when TMDB's language list cannot be fetched.
_FALLBACK_LANGUAGES = {
    "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic",
    "hy": "Armenian", "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian",
    "bn": "Bengali", "bs": "Bosnian", "bg": "Bulgarian", "my": "Burmese",
    "ca": "Catalan", "zh": "Chinese (Mandarin)", "cn": "Chinese (Cantonese)",
    "hr": "Croatian", "cs": "Czech", "da": "Danish", "nl": "Dutch",
    "en": "English", "et": "Estonian", "tl": "Filipino", "fi": "Finnish",
    "fr": "French", "gl": "Galician", "ka": "Georgian", "de": "German",
    "el": "Greek", "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi",
    "hu": "Hungarian", "is": "Icelandic", "id": "Indonesian", "ga": "Irish",
    "it": "Italian", "ja": "Japanese", "kn": "Kannada", "kk": "Kazakh",
    "km": "Khmer", "ko": "Korean", "ku": "Kurdish", "lo": "Lao",
    "lv": "Latvian", "lt": "Lithuanian", "mk": "Macedonian", "ms": "Malay",
    "ml": "Malayalam", "mt": "Maltese", "mr": "Marathi", "mn": "Mongolian",
    "ne": "Nepali", "no": "Norwegian", "fa": "Persian", "pl": "Polish",
    "pt": "Portuguese", "pa": "Punjabi", "ro": "Romanian", "ru": "Russian",
    "sr": "Serbian", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian",
    "es": "Spanish", "sw": "Swahili", "sv": "Swedish", "ta": "Tamil",
    "te": "Telugu", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese", "cy": "Welsh",
    "yo": "Yoruba", "zu": "Zulu",
}


@st.cache_data(ttl=GENRE_CACHE_TTL, show_spinner=False)
def get_languages() -> dict[str, str]:
    """Map of ISO 639-1 code -> English language name, sorted A-Z by name.

    Uses TMDB's live language list; falls back to a built-in list if TMDB is
    unreachable so the selector never goes empty.
    """
    languages: dict[str, str] = {}
    try:
        for entry in _get("configuration/languages", {}):
            code = (entry.get("iso_639_1") or "").strip()
            name = (entry.get("english_name") or "").strip()
            if code and name and code != "xx" and name.lower() != "no language":
                languages[code] = name
    except Exception:
        languages = {}
    if len(languages) < 20:
        languages = dict(_FALLBACK_LANGUAGES)
    return dict(sorted(languages.items(), key=lambda kv: kv[1].casefold()))
