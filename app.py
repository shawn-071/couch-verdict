"""Couch Verdict — find a movie everyone can agree on."""

from __future__ import annotations

import json

import streamlit as st

from services import db, recommender, tmdb_client
from services.recommender import AUDIENCE_CERT_CEILING, MovieMatch

st.set_page_config(
    page_title="Couch Verdict",
    page_icon="🍿",
    layout="wide",
    initial_sidebar_state="expanded",
)

REGIONS = {
    "United States": "US",
    "United Kingdom": "GB",
    "Qatar": "QA",
    "Saudi Arabia": "SA",
    "United Arab Emirates": "AE",
    "Canada": "CA",
    "Australia": "AU",
    "India": "IN",
    "Egypt": "EG",
    "France": "FR",
    "Germany": "DE",
    "Turkey": "TR",
}

RUNTIME_OPTIONS = {
    "Any length": None,
    "Under 90 minutes": 90,
    "Under 2 hours": 120,
}

ERA_OPTIONS = {
    "Any release year": None,
    "2010 or newer": 2010,
    "2015 or newer": 2015,
    "2020 or newer": 2020,
}

LANGUAGE_OPTIONS = {
    "Any language": None,
    "English": "en",
    "Arabic": "ar",
    "Hindi": "hi",
    "French": "fr",
    "Spanish": "es",
    "Turkish": "tr",
}

AUDIENCES = {
    "Kids only": "kids",
    "Teens & mixed group": "mixed",
    "Adults only": "adults",
}

VOTE_CHOICES = ["Watch this", "Maybe", "Pass"]


# ---------------------------------------------------------------- helpers

def init_session() -> None:
    defaults = {
        "page": "home",
        "user": None,          # {"id": int, "name": str}
        "results": None,       # list[MovieMatch]
        "relax_notes": [],
        "night_id": None,
        "votes": {},           # movie_id -> {choice: count}
        "verdict": None,       # winning MovieMatch
        "search_error": None,
        "search_started": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def go(page: str) -> None:
    st.session_state.page = page
    st.rerun()


def genre_names(ids: list[int]) -> str:
    try:
        genres = tmdb_client.get_genres()
    except Exception:
        return ""
    return " · ".join(genres.get(gid, "") for gid in ids if gid)


def movie_card(match: MovieMatch, index: int) -> None:
    user = st.session_state.user
    poster = tmdb_client.poster_url(match.poster_path)
    col_poster, col_info = st.columns([1, 3])

    with col_poster:
        if poster:
            st.image(poster, width="stretch")
        else:
            st.markdown("<div style='height:200px'></div>", unsafe_allow_html=True)

    with col_info:
        badge = (
            "<span style='background:#22c55e;color:#fff;padding:2px 10px;"
            "border-radius:12px;font-size:0.75rem'>Exact match</span>"
            if match.match_label == "Exact match"
            else f"<span style='background:#f59e0b;color:#fff;padding:2px 10px;"
                 f"border-radius:12px;font-size:0.75rem'>{match.match_label}</span>"
        )
        st.markdown(
            f"<span style='color:#0f172a;font-size:1.4rem;font-weight:700'>"
            f"{match.title}</span>&nbsp;&nbsp;{badge}",
            unsafe_allow_html=True,
        )
        meta_bits = [match.year or "—", match.runtime_text]
        if match.certification:
            meta_bits.append(match.certification)
        st.markdown(
            "<span style='color:#475569'>" + " · ".join(meta_bits) + "</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<span style='color:#475569'>{genre_names(match.genre_ids)}</span>",
            unsafe_allow_html=True,
        )
        if match.providers:
            st.markdown(
                "<span style='color:#0f766e'>Available on: "
                + ", ".join(match.providers[:4])
                + "</span>",
                unsafe_allow_html=True,
            )
        elif st.session_state.results and match.match_label.startswith("Near match — popular"):
            st.markdown(
                "<span style='color:#94a3b8'>Not filtered to your services</span>",
                unsafe_allow_html=True,
            )

        bottom = st.columns([2, 1])
        with bottom[0]:
            bar_color = "#22c55e" if match.match_pct >= 90 else "#f59e0b"
            st.markdown(
                f"<div style='background:#e2e8f0;border-radius:6px;height:10px;width:100%'>"
                f"<div style='background:{bar_color};border-radius:6px;height:10px;"
                f"width:{match.match_pct}%'></div></div>"
                f"<span style='color:#475569;font-size:0.8rem'>{match.match_pct}% match</span>",
                unsafe_allow_html=True,
            )
        with bottom[1]:
            if user:
                saved = db.is_saved(user["id"], match.movie_id)
                if st.button(
                    "Saved ✓" if saved else "Save",
                    key=f"save_{index}_{match.movie_id}",
                    width="stretch",
                ):
                    if saved:
                        db.unsave_movie(user["id"], match.movie_id)
                    else:
                        db.save_movie(
                            user["id"], match.movie_id, match.title,
                            match.poster_path, match.year, match.providers,
                        )
                    st.rerun()
    st.markdown("<hr style='margin:0.5rem 0;border:none;border-top:1px solid #e2e8f0'>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- pages

def page_home() -> None:
    st.markdown(
        "<div style='text-align:center;padding:2rem 0 1rem'>"
        "<span style='font-size:2.6rem;font-weight:800;color:#0f172a'>🍿 Couch Verdict</span><br>"
        "<span style='font-size:1.15rem;color:#475569'>Find a movie everyone can agree on — "
        "in under two minutes.</span></div>",
        unsafe_allow_html=True,
    )

    stats = db.get_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Movie nights", stats["movie_nights"])
    c2.metric("Movies recommended", stats["recommendations"])
    c3.metric("Group votes cast", stats["votes"])
    c4.metric("Movies saved", stats["saved"])
    c5.metric("Movie lovers joined", stats["movie_lovers"])
    st.caption(
        "Live activity for this deployment instance (resets if the app container restarts)."
    )

    st.markdown(
        "<div style='text-align:center;padding:1.5rem 0'>"
        "<span style='color:#94a3b8'>No more endless scrolling across Netflix, Disney+, "
        "Prime Video and the rest. Pick your services, set your group's limits, and get "
        "exactly five movies that fit — then let the group vote.</span></div>",
        unsafe_allow_html=True,
    )
    center = st.columns([2, 1, 2])
    with center[1]:
        if st.button("Start a movie night", type="primary", width="stretch"):
            if not st.session_state.user:
                st.toast("Enter your name in the sidebar first so the group has a host.")
            else:
                go("preferences")


def page_preferences() -> None:
    st.header("Set up your movie night")

    if st.session_state.search_error:
        st.error(st.session_state.search_error)
        st.session_state.search_error = None

    with st.form("prefs"):
        region_label = st.selectbox("Where do you stream?", list(REGIONS.keys()), index=0)
        region = REGIONS[region_label]

        try:
            providers = tmdb_client.get_providers(region)
        except tmdb_client.TMDBConfigError as exc:
            st.error(str(exc))
            st.stop()
        except tmdb_client.TMDBApiError as exc:
            st.error(f"Could not load streaming services from TMDB: {exc}")
            st.stop()

        popular = [name for name in [
            "Netflix", "Prime Video", "Disney Plus", "Apple TV+", "Apple TV",
            "Max", "Hulu", "Paramount+",
        ] if name in providers]
        other = [name for name in providers if name not in popular]
        options = popular + sorted(other)

        services = st.multiselect(
            "Which services do you have?", options,
            default=[s for s in popular[:4] if s in options],
            max_selections=8,
        )

        audience_label = st.radio("Who is watching?", list(AUDIENCES.keys()), index=1)
        ceiling = AUDIENCE_CERT_CEILING[AUDIENCES[audience_label]]
        if ceiling:
            st.caption(
                f"US age rating limit: {ceiling} or below. "
                "Movies without a verified rating are never shown as kid-safe."
            )
        else:
            st.caption("No age limit — adult audience.")

        try:
            genres = tmdb_client.get_genres()
        except tmdb_client.TMDBApiError as exc:
            st.error(f"Could not load genres from TMDB: {exc}")
            st.stop()
        genre_names_sorted = sorted(genres.values())
        chosen_genres = st.multiselect(
            "Pick up to 3 genres", genre_names_sorted, max_selections=3
        )

        runtime_label = st.radio("How much time do you have?", list(RUNTIME_OPTIONS.keys()))
        max_runtime = RUNTIME_OPTIONS[runtime_label]

        era_label = st.selectbox("Release year", list(ERA_OPTIONS.keys()))
        min_year = ERA_OPTIONS[era_label]

        lang_label = st.selectbox("Language", list(LANGUAGE_OPTIONS.keys()))
        language = LANGUAGE_OPTIONS[lang_label]

        submitted = st.form_submit_button("Find our 5 movies", type="primary", width="stretch")

    if submitted:
        if not services:
            st.error("Select at least one streaming service.")
            st.session_state.search_error = "Select at least one streaming service."
            st.rerun()
        if len(chosen_genres) < 1:
            st.session_state.search_error = "Pick at least one genre (up to three)."
            st.rerun()

        user = st.session_state.user
        st.session_state.search_started = True
        prefs = {
            "region": region,
            "services": services,
            "audience": AUDIENCES[audience_label],
            "genres": chosen_genres,
            "max_runtime": max_runtime,
            "min_year": min_year,
            "language": language,
        }
        night_id = db.create_movie_night(user["id"], prefs)
        st.session_state.night_id = night_id

        provider_ids = [providers[s] for s in services]
        genre_ids = [gid for gid, gname in genres.items() if gname in chosen_genres]

        with st.spinner("Searching every service you have..."):
            try:
                matches, notes = recommender.find_five_movies(
                    genre_ids=genre_ids,
                    provider_ids=provider_ids,
                    region=region,
                    max_runtime=max_runtime,
                    cert_ceiling=ceiling,
                    min_year=min_year,
                    language=language,
                )
            except tmdb_client.TMDBConfigError as exc:
                st.session_state.search_error = str(exc)
                st.session_state.search_started = False
                st.rerun()
            except tmdb_client.TMDBApiError as exc:
                st.session_state.search_error = f"TMDB is not responding right now: {exc}"
                st.session_state.search_started = False
                st.rerun()

        if not matches:
            st.session_state.search_error = (
                "TMDB returned no age-suitable movies at all for these settings. "
                "Try a different region or service combination."
            )
            st.session_state.search_started = False
            st.rerun()

        db.record_recommendations(night_id, matches)
        st.session_state.results = matches
        st.session_state.relax_notes = notes
        st.session_state.votes = {}
        st.session_state.verdict = None
        go("results")


def page_results() -> None:
    matches: list[MovieMatch] = st.session_state.results or []
    if not matches:
        go("preferences")
        return

    st.header("Your 5 matches")
    st.caption(
        "Ordered best-match first. Green badge = matches every preference. "
        "Orange badge = a near match (the badge says which preference was relaxed)."
    )

    if len(matches) < 5:
        st.warning(
            f"Only {len(matches)} movie(s) could be verified as age-suitable for these "
            "settings. The age limit is never relaxed — try adding more services or "
            "widening the time limit."
        )

    for i, match in enumerate(matches):
        movie_card(match, i)

    left, right = st.columns(2)
    with left:
        if st.button("Start the group vote", type="primary", width="stretch"):
            go("vote")
    with right:
        if st.button("Change preferences", width="stretch"):
            st.session_state.results = None
            go("preferences")


def page_vote() -> None:
    matches: list[MovieMatch] = st.session_state.results or []
    if not matches:
        go("preferences")
        return

    votes: dict = st.session_state.votes

    if st.session_state.verdict is None:
        st.header("Group vote")
        st.markdown(
            "<span style='color:#475569'>Everyone votes on every movie: "
            "**Watch this**, **Maybe** or **Pass**. Most 'Watch this' wins.</span>",
            unsafe_allow_html=True,
        )

        voter = st.text_input(
            "Voter name (each person votes, one at a time)",
            value=st.session_state.user["name"] if st.session_state.user else "",
            key="voter_name",
        )

        progress = st.progress(0.0)
        total_votes = sum(sum(choices.values()) for choices in votes.values())
        expected = len(matches) * 3
        progress.progress(min(1.0, total_votes / expected) if expected else 0.0)

        for i, match in enumerate(matches):
            tally = votes.get(match.movie_id, {"Watch this": 0, "Maybe": 0, "Pass": 0})
            col1, col2 = st.columns([3, 2])
            with col1:
                st.markdown(
                    f"<span style='font-weight:700'>{match.title}</span> "
                    f"<span style='color:#475569'>({match.year or '—'})</span>",
                    unsafe_allow_html=True,
                )
            with col2:
                clicked = None
                b1, b2, b3 = st.columns(3)
                if b1.button("Watch this", key=f"v{i}_w", width="stretch",
                              type="primary"):
                    clicked = "Watch this"
                if b2.button("Maybe", key=f"v{i}_m", width="stretch"):
                    clicked = "Maybe"
                if b3.button("Pass", key=f"v{i}_p", width="stretch"):
                    clicked = "Pass"
            if clicked:
                if not voter.strip():
                    st.toast("Enter a voter name first.")
                    st.rerun()
                tally[clicked] += 1
                votes[match.movie_id] = tally
                db.record_vote(
                    st.session_state.night_id, match.movie_id, match.title,
                    clicked, voter.strip(),
                )
                st.rerun()
            st.markdown(
                "<span style='color:#94a3b8;font-size:0.8rem'>"
                + " · ".join(f"{c}: {tally[c]}" for c in VOTE_CHOICES)
                + "</span>",
                unsafe_allow_html=True,
            )
            st.markdown("<hr style='margin:0.3rem 0;border:none;border-top:1px solid #e2e8f0'>",
                        unsafe_allow_html=True)

        if st.button("Show the verdict", type="primary", width="stretch"):
            winner = None
            best = (-1, -1)
            for match in matches:
                t = votes.get(match.movie_id, {"Watch this": 0, "Maybe": 0, "Pass": 0})
                score = (t["Watch this"], t["Maybe"])
                if score > best:
                    best = score
                    winner = match
            if best == (-1, -1):
                st.toast("No votes yet — cast at least one vote first.")
            else:
                st.session_state.verdict = winner
                st.rerun()

        if st.button("Back to results", width="stretch"):
            go("results")
    else:
        winner: MovieMatch = st.session_state.verdict
        poster = tmdb_client.poster_url(winner.poster_path)
        col1, col2 = st.columns([1, 2])
        with col1:
            if poster:
                st.image(poster, width="stretch")
        with col2:
            st.markdown(
                "<span style='color:#16a34a;font-weight:700'>THE VERDICT</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<span style='font-size:2rem;font-weight:800'>{winner.title}</span> "
                f"<span style='color:#475569'>({winner.year or '—'})</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<span style='color:#475569'>{winner.runtime_text}"
                + (f" · {winner.certification}" if winner.certification else "")
                + f" · {genre_names(winner.genre_ids)}</span>",
                unsafe_allow_html=True,
            )
            if winner.providers:
                st.markdown(
                    "<span style='color:#0f766e'>Watch it on: " + ", ".join(winner.providers[:4]) + "</span>",
                    unsafe_allow_html=True,
                )
            st.markdown(f"<span style='color:#475569'>{winner.overview}</span>",
                        unsafe_allow_html=True)

        user = st.session_state.user
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Save this movie", width="stretch"):
            db.save_movie(user["id"], winner.movie_id, winner.title,
                          winner.poster_path, winner.year, winner.providers)
            st.toast("Saved to your watchlist.")
        if b2.button("Start another vote", width="stretch"):
            st.session_state.votes = {}
            st.session_state.verdict = None
            st.rerun()
        if b3.button("Change preferences", width="stretch"):
            st.session_state.results = None
            st.session_state.verdict = None
            go("preferences")
        if b4.button("Share result", width="stretch"):
            share_text = (
                f"Couch Verdict picked: {winner.title} ({winner.year}) — "
                f"{winner.runtime_text}"
                + (f", rated {winner.certification}" if winner.certification else "")
                + ". We voted and everyone agreed."
            )
            st.code(share_text, language=None)
            st.toast("Copy the text above to share.")


def page_saved() -> None:
    st.header("Saved movies")
    user = st.session_state.user
    if not user:
        st.info("Join with your name in the sidebar to save movies.")
        return
    rows = db.get_saved_movies(user["id"])
    if not rows:
        st.info("No saved movies yet. Save one from your results.")
        return
    for row in rows:
        col1, col2 = st.columns([1, 4])
        with col1:
            poster = tmdb_client.poster_url(row["poster_path"])
            if poster:
                st.image(poster, width="stretch")
        with col2:
            st.markdown(
                f"<span style='font-weight:700'>{row['title']}</span> "
                f"<span style='color:#475569'>({row['year'] or '—'})</span>",
                unsafe_allow_html=True,
            )
            try:
                names = ", ".join(json.loads(row["providers"] or "[]"))
            except Exception:
                names = ""
            if names:
                st.markdown(
                    f"<span style='color:#0f766e'>On: {names}</span>",
                    unsafe_allow_html=True,
                )
            if st.button("Remove", key=f"rm_{row['movie_id']}"):
                db.unsave_movie(user["id"], row["movie_id"])
                st.rerun()
        st.markdown("<hr style='margin:0.4rem 0;border:none;border-top:1px solid #e2e8f0'>",
                    unsafe_allow_html=True)


# ---------------------------------------------------------------- layout

def main() -> None:
    db.init_db()
    init_session()

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 900px; }
        div[data-testid="stSidebar"] { background: #0f172a; }
        div[data-testid="stSidebar"] * { color: #e2e8f0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            "<span style='font-size:1.2rem;font-weight:800'>🍿 Couch Verdict</span><br>"
            "<span style='color:#94a3b8'>The unified family movie filter</span>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        if st.session_state.user:
            st.markdown(
                f"<span style='color:#22c55e;font-weight:700'>●</span> "
                f"<b>{st.session_state.user['name']}</b>",
                unsafe_allow_html=True,
            )
            if st.button("Log out", width="stretch"):
                st.session_state.user = None
                st.session_state.results = None
                go("home")
        else:
            with st.form("login"):
                st.markdown("**Sign in to host tonight's movie night**")
                name = st.text_input("Your name", key="login_name")
                password = st.text_input(
                    "Password", type="password", key="login_password"
                )
                c1, c2 = st.columns(2)
                sign_in = c1.form_submit_button("Sign in", width="stretch", type="primary")
                create = c2.form_submit_button("Create account", width="stretch")
            if sign_in:
                user_id, error = db.login_user(name, password)
                if error:
                    st.toast(error)
                else:
                    st.session_state.user = {"id": user_id, "name": name.strip()}
                    st.rerun()
            if create:
                user_id, error = db.register_user(name, password)
                if error:
                    st.toast(error)
                else:
                    st.session_state.user = {"id": user_id, "name": name.strip()}
                    st.rerun()
            st.caption(
                "Accounts live in the app's database (guests can still vote by "
                "typing a name during the vote)."
            )

        st.markdown("---")
        nav = {
            "Home": "home",
            "New movie night": "preferences",
            "Saved movies": "saved",
        }
        cols = st.columns(3)
        for i, (label, target) in enumerate(nav.items()):
            if cols[i].button(label, width="stretch",
                              key=f"nav_{target}"):
                if target == "preferences" and not st.session_state.user:
                    st.toast("Enter your name first.")
                else:
                    go(target)

        st.markdown(
            "<span style='color:#64748b;font-size:0.7rem'>Movie data from "
            "<a href='https://www.themoviedb.org' style='color:#64748b'>TMDB</a>. "
            "US age ratings (G / PG / PG-13).</span>",
            unsafe_allow_html=True,
        )

    pages = {
        "home": page_home,
        "preferences": page_preferences,
        "results": page_results,
        "vote": page_vote,
        "saved": page_saved,
    }
    pages[st.session_state.page]()


main()
