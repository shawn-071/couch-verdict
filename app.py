"""Couch Verdict V.5.0: a simple, mobile-first group movie picker."""
from __future__ import annotations

import base64
import random
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from services import db, recommender, tmdb_client
from services.recommender import MovieMatch

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "assets" / "couch-verdict-logo.png"
LOGO_BUTTON_PATH = APP_DIR / "assets" / "couch-verdict-logo-button.png"

st.set_page_config(
    page_title="Couch Verdict",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

RUNTIME_OPTIONS = {"Any length": None, "Up to 90 minutes": 90, "Up to 2 hours": 120}
DECADE_OPTIONS = {
    "1980s": 1980,
    "1990s": 1990,
    "2000s": 2000,
    "2010s": 2010,
    "2020s": 2020,
}


def init_session() -> None:
    defaults = {
        "page": "home",
        "preferences": None,
        "members": [],
        "member_draft": "",
        "member_error": None,
        "results": [],
        "relax_notes": [],
        "night_id": None,
        "member_picks": {},
        "turn_index": 0,
        "verdict": None,
        "random_animation": False,
        "search_error": None,
        "member_search_error": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    # Keep the current view mirrored in the URL so browser Back/Forward can
    # restore earlier app steps instead of leaving the app stuck on one view.
    valid_pages = {"home", "preferences", "members", "results", "vote", "verdict"}
    try:
        url_page = st.query_params.get("page")
        if url_page in valid_pages:
            st.session_state.page = url_page
        elif not url_page:
            st.session_state.page = "home"
    except Exception:
        # Session-state navigation remains available on older Streamlit versions.
        pass


def go(page: str) -> None:
    st.session_state.page = page
    try:
        st.query_params["page"] = page
    except Exception:
        pass
    st.rerun()


def clear_vote_widget_state() -> None:
    for i in range(max(1, len(st.session_state.members)) + 2):
        st.session_state.pop(f"turn_choice_{i}", None)


def reset_everything() -> None:
    clear_vote_widget_state()
    st.session_state.preferences = None
    st.session_state.members = []
    st.session_state.member_draft = ""
    st.session_state.member_error = None
    st.session_state.results = []
    st.session_state.relax_notes = []
    st.session_state.night_id = None
    st.session_state.member_picks = {}
    st.session_state.turn_index = 0
    st.session_state.verdict = None
    st.session_state.random_animation = False
    st.session_state.search_error = None
    st.session_state.member_search_error = None
    go("home")


def add_member_callback() -> None:
    candidate = str(st.session_state.get("member_draft", "")).strip()
    st.session_state.member_error = None
    if not candidate:
        st.session_state.member_error = "Type a name before tapping Add member."
    elif any(candidate.casefold() == name.casefold() for name in st.session_state.members):
        st.session_state.member_error = "That name is already on the list. Choose a different name."
    else:
        st.session_state.members.append(candidate)
        st.session_state.member_draft = ""


def remove_member_callback(index: int) -> None:
    members = list(st.session_state.members)
    if 0 <= index < len(members):
        members.pop(index)
    st.session_state.members = members
    st.session_state.member_error = None


def render_top_nav() -> None:
    """Show a compatible clickable logo button at the top-left of each screen.

    Streamlit has no dedicated image-button widget in its public API. This uses
    the stable st.button API and paints the button with the current logo using CSS.
    """
    logo_col, brand_col, _spacer = st.columns([1.0, 3.0, 6.0], vertical_alignment="center", gap="small")
    with logo_col:
        if st.button(
            "Home",
            help="Return to the Couch Verdict home page",
            key="global_logo_home_button",
            type="secondary",
        ):
            go("home")
    with brand_col:
        st.markdown("<div class='brand-wordmark'>COUCH VERDICT</div>", unsafe_allow_html=True)


def get_genre_label(ids: list[int]) -> str:
    try:
        genres = tmdb_client.get_genres()
        return " · ".join(genres.get(gid, "") for gid in ids if genres.get(gid))
    except Exception:
        return ""


def render_movie_card(match: MovieMatch, index: int) -> None:
    with st.container():
        left, right = st.columns([0.9, 2.3], gap="medium")
        with left:
            poster = tmdb_client.poster_url(match.poster_path)
            if poster:
                st.image(poster, width=120)
            else:
                st.image(str(LOGO_PATH), width=120)
        with right:
            st.markdown(f"**{index}. {match.title}**")
            details = [match.year or "Year unknown", match.runtime_text]
            if match.certification:
                details.append(match.certification)
            st.caption(" · ".join(details))
            st.markdown(f"⭐ **{match.vote_average:.1f}/10**  ·  {match.match_label}")
            genre_text = get_genre_label(match.genre_ids)
            if genre_text:
                st.caption(genre_text)
            if match.providers:
                st.caption("Streaming on: " + ", ".join(match.providers[:4]))
            if match.overview:
                overview = match.overview.strip()
                if len(overview) > 190:
                    overview = overview[:187].rsplit(" ", 1)[0] + "…"
                st.write(overview)
        st.divider()


# The figures below are intentionally fictional. They are a small brand flourish,
# not analytics collected from app users. The formula assumes 480 groups per day
# each spend 18 minutes deciding, or 144 aggregate person-hours per day.
MODEL_GROUPS_PER_DAY = 480
MODEL_MINUTES_PER_GROUP = 18
MODEL_HOURS_PER_DAY = MODEL_GROUPS_PER_DAY * MODEL_MINUTES_PER_GROUP / 60
MODEL_TRACKING_START = (2025, 1, 1)


def estimate_hours_since(start: datetime, now: datetime) -> float:
    """Calculate the playful simulated aggregate counter for a period."""
    elapsed_seconds = max(0.0, (now - start).total_seconds())
    return elapsed_seconds / 86400 * MODEL_HOURS_PER_DAY


@st.fragment(run_every="3s")
def render_waste_stats() -> None:
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    all_time_start = now.replace(
        year=MODEL_TRACKING_START[0], month=MODEL_TRACKING_START[1],
        day=MODEL_TRACKING_START[2], hour=0, minute=0, second=0, microsecond=0,
    )

    stats = [
        ("Today", estimate_hours_since(today_start, now)),
        ("This week", estimate_hours_since(week_start, now)),
        ("This month", estimate_hours_since(month_start, now)),
        ("This year", estimate_hours_since(year_start, now)),
        ("All time", estimate_hours_since(all_time_start, now)),
    ]
    st.markdown("### The global movie-decision tax")
    for columns, items in ((st.columns(2), stats[:2]), (st.columns(2), stats[2:4])):
        for column, (label, hours) in zip(columns, items):
            with column:
                st.metric(label, f"{hours:,.2f} h")
    left, center, right = st.columns([1, 2, 1])
    with center:
        st.metric(stats[4][0], f"{stats[4][1]:,.2f} h")


def page_home() -> None:
    st.markdown("<div class='hero-kicker'>MOVIE NIGHT, SORTED</div>", unsafe_allow_html=True)
    logo_col, title_col = st.columns([1, 3.8], vertical_alignment="center", gap="small")
    with logo_col:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=88)
    with title_col:
        st.title("Couch Verdict")
    st.markdown(
        "Five contenders. One couch jury. Finally, a decision before the snacks disappear."
    )
    st.markdown(
        "<div class='hero-panel'><div class='hero-number'>5</div>"
        "<div><strong>movies to choose from</strong><br>"
        "<span>One shared shortlist. One final verdict.</span></div></div>",
        unsafe_allow_html=True,
    )
    render_waste_stats()
    st.write("")
    if st.button("Start a movie night", type="primary", use_container_width=True):
        go("preferences")
    st.caption("Movie information and ratings supplied by TMDB.")


def page_preferences() -> None:
    st.markdown("<div class='step-label'>STEP 1 OF 4</div>", unsafe_allow_html=True)
    st.title("Set the vibe")
    st.write("Choose the services and limits everyone can live with.")

    # The region, language, and age-rating catalogues are pulled from TMDB so
    # the choices track the API instead of aging into an incomplete static list.
    try:
        with st.spinner("Loading countries, languages, ratings and movie filters…"):
            region_map = tmdb_client.get_regions()
            languages = tmdb_client.get_languages()
            certification_map = tmdb_client.get_movie_certifications()
        genres = tmdb_client.get_genres()
    except tmdb_client.TMDBConfigError as exc:
        st.error(str(exc))
        st.info("The app owner needs to add a TMDB API key in Streamlit app settings → Secrets.")
        if st.button("Back home", use_container_width=True):
            go("home")
        return
    except tmdb_client.TMDBApiError as exc:
        st.error(f"TMDB could not load the preferences: {exc}")
        st.info("Check your connection, then refresh the app.")
        if st.button("Back home", use_container_width=True):
            go("home")
        return

    if not region_map:
        st.error("TMDB did not return any supported streaming regions. Please try again later.")
        if st.button("Back home", use_container_width=True):
            go("home")
        return

    region_names = sorted(region_map, key=str.casefold)
    # Keep the preferred Qatar default where TMDB offers it; otherwise use the
    # first region supplied by TMDB.
    default_region = next((name for name in region_names if name.casefold() == "qatar"), region_names[0])

    with st.container(border=True, key="preferences-card"):
        region_label = st.selectbox(
            "Where do you stream?", region_names,
            index=region_names.index(default_region),
            key="streaming_region",
        )
        region_code = region_map[region_label]

        try:
            with st.spinner("Loading streaming services…"):
                providers = tmdb_client.get_providers(region_code)
        except tmdb_client.TMDBConfigError as exc:
            st.error(str(exc))
            if st.button("Back home", use_container_width=True):
                go("home")
            return
        except tmdb_client.TMDBApiError as exc:
            st.error(f"Could not load streaming services for {region_label}: {exc}")
            if st.button("Back home", use_container_width=True):
                go("home")
            return

        # The certification options vary by country. Reset the prior country's
        # values when region changes so stale choices cannot leak across systems.
        if st.session_state.get("_age_rating_region") != region_code:
            st.session_state["age_rating_picker"] = ["Any rating"]
            st.session_state["_age_rating_region"] = region_code
        st.session_state.setdefault("age_rating_picker", ["Any rating"])

        country_certifications = certification_map.get(region_code, [])
        # If TMDB has no certification catalogue for the streaming region, use
        # US ratings as a fallback while continuing to search streaming providers
        # in the user's actual region.
        rating_region_code = region_code if country_certifications else "US"
        rating_certifications = (
            country_certifications if country_certifications
            else certification_map.get("US", [])
        )
        rating_codes = [item["certification"] for item in rating_certifications]
        rating_choices = ["Any rating", *rating_codes]
        rating_system_label = (
            region_label if country_certifications else "United States (fallback)"
        )
        language_map = {
            f'{item["name"]} ({item["code"]})': item["code"]
            for item in languages
        }
        language_options = {"Any language": None, **language_map}

        # Reset decade state when deploying this major release, but preserve it
        # during normal reruns so the form remains pleasant to use.
        if st.session_state.get("_release_decade_picker_version") != "5.0":
            st.session_state["release_decade_picker"] = []
            st.session_state["_release_decade_picker_version"] = "5.0"
        st.session_state.setdefault("release_decade_picker", [])

        with st.form("preferences_form"):
            popular = [name for name in [
                "Netflix", "Prime Video", "Disney Plus", "Apple TV+", "Apple TV",
                "Max", "Hulu", "Paramount+",
            ] if name in providers]
            services_available = popular + sorted(name for name in providers if name not in popular)
            chosen_services = st.multiselect(
                "Which streaming services do you have?",
                services_available,
                default=popular[:4],
                max_selections=8,
                placeholder="Choose up to 8 services",
            )

            rating_selection = st.multiselect(
                "Age rating",
                rating_choices,
                key="age_rating_picker",
                placeholder="Choose Any rating or one or more ratings",
                help=(
                    f"Ratings use {rating_system_label}. "
                    "For regions without their own TMDB certification list, US ratings are used."
                ),
                select_all=False,
            )
            if not country_certifications:
                st.caption("This region has no TMDB rating list. US ratings are used as a fallback.")

            genre_names = sorted(genres.values())
            chosen_genres = st.multiselect(
                "Pick up to 3 genres", genre_names, max_selections=3,
                placeholder="Comedy, animation, sci-fi…",
            )
            decade_choices = ["Any decade", *DECADE_OPTIONS.keys()]
            decade_selection = st.multiselect(
                "Release decades",
                decade_choices,
                key="release_decade_picker",
                placeholder="Choose Any decade or specific decades",
                help="Choose Any decade by itself, or select one or more specific decades.",
                select_all=False,
            )
            c1, c2 = st.columns(2)
            with c1:
                runtime_label = st.selectbox("Maximum movie length", list(RUNTIME_OPTIONS.keys()))
            with c2:
                lang_label = st.selectbox("Movie language", list(language_options.keys()))
            submitted = st.form_submit_button(
                "Next: add members", type="primary", use_container_width=True
            )

    if submitted:
        if not rating_selection:
            st.error("Choose Any rating or select at least one age rating before continuing.")
            return
        if "Any rating" in rating_selection and len(rating_selection) > 1:
            st.error("Choose Any rating by itself, or select one or more specific ratings.")
            return
        if not decade_selection:
            st.error("Choose Any decade or select at least one release decade before continuing.")
            return
        if "Any decade" in decade_selection and len(decade_selection) > 1:
            st.error("Choose Any decade by itself, or select one or more specific decades.")
            return
        chosen_decades = [value for value in decade_selection if value != "Any decade"]
        if not chosen_services:
            st.error("Choose at least one streaming service.")
            return
        if not chosen_genres:
            st.error("Choose at least one genre.")
            return

        allowed_certifications = None if "Any rating" in rating_selection else rating_selection
        st.session_state.preferences = {
            "region": region_code,
            "region_label": region_label,
            "services": chosen_services,
            "allowed_certifications": allowed_certifications,
            "rating_region": rating_region_code,
            "rating_labels": rating_selection,
            "genres": chosen_genres,
            "max_runtime": RUNTIME_OPTIONS[runtime_label],
            "release_decades": [DECADE_OPTIONS[label] for label in chosen_decades],
            "language": language_options[lang_label],
            "language_label": lang_label,
        }
        st.session_state.results = []
        st.session_state.verdict = None
        st.session_state.member_search_error = None
        go("members")

    if st.button("Back home", use_container_width=True):
        go("home")


def page_members() -> None:
    if not st.session_state.preferences:
        go("preferences")
        return
    st.markdown("<div class='step-label'>STEP 2 OF 4</div>", unsafe_allow_html=True)
    st.title("Who's on the couch?")
    st.write("Add everyone who's voting. Pass the phone around when the voting starts.")

    with st.form("add_member_form"):
        st.text_input("Member name", key="member_draft", placeholder="e.g. Sam")
        st.form_submit_button("Add member", on_click=add_member_callback, use_container_width=True)

    if st.session_state.member_error:
        st.warning(st.session_state.member_error)
    if st.session_state.members:
        st.markdown(f"**On the list · {len(st.session_state.members)}**")
        for i, name in enumerate(list(st.session_state.members)):
            col_name, col_remove = st.columns([4, 1])
            with col_name:
                st.markdown(f"<div class='member-row'>{name}</div>", unsafe_allow_html=True)
            with col_remove:
                st.button("Remove", key=f"remove_member_{i}", on_click=remove_member_callback, args=(i,))
    else:
        st.info("No members added yet. Add at least one person to continue.")

    st.write("")
    if st.button("Next: find our 5 movies", type="primary", use_container_width=True):
        if not st.session_state.members:
            st.session_state.member_search_error = "Add at least one member first."
        else:
            st.session_state.member_search_error = None
            prefs = st.session_state.preferences
            try:
                with st.spinner("Finding movies that fit your group's preferences…"):
                    db.init_db()
                    night_id = db.create_movie_night(None, prefs)
                    providers = tmdb_client.get_providers(prefs["region"])
                    genres = tmdb_client.get_genres()
                    provider_ids = [providers[name] for name in prefs["services"] if name in providers]
                    genre_ids = [gid for gid, name in genres.items() if name in prefs["genres"]]
                    matches, notes = recommender.find_five_movies(
                        genre_ids=genre_ids,
                        provider_ids=provider_ids,
                        region=prefs["region"],
                        max_runtime=prefs["max_runtime"],
                        allowed_certifications=prefs.get("allowed_certifications"),
                        rating_region=prefs.get("rating_region", prefs["region"]),
                        release_decades=prefs.get("release_decades", []),
                        language=prefs["language"],
                    )
                if not matches:
                    st.session_state.member_search_error = (
                        "TMDB couldn't find any movies verified for these settings. "
                        "Try a different service, genre, or time limit."
                    )
                else:
                    db.record_recommendations(night_id, matches)
                    st.session_state.night_id = night_id
                    st.session_state.results = matches
                    st.session_state.relax_notes = notes
                    st.session_state.member_picks = {}
                    st.session_state.turn_index = 0
                    st.session_state.verdict = None
                    st.session_state.member_search_error = None
                    clear_vote_widget_state()
                    go("results")
            except tmdb_client.TMDBConfigError as exc:
                st.session_state.member_search_error = str(exc)
            except tmdb_client.TMDBApiError as exc:
                st.session_state.member_search_error = f"TMDB is not responding right now: {exc}"
            except Exception as exc:
                st.session_state.member_search_error = f"Something went wrong while finding movies: {exc}"

    # Render feedback before the navigation action, including after empty results.
    if st.session_state.get("member_search_error"):
        st.error(st.session_state.member_search_error)
    if st.button("Back to preferences", use_container_width=True):
        st.session_state.member_search_error = None
        go("preferences")

def page_results() -> None:
    matches: list[MovieMatch] = st.session_state.results or []
    if not matches:
        go("members")
        return
    st.markdown("<div class='step-label'>STEP 3 OF 4</div>", unsafe_allow_html=True)
    st.title("Your movie shortlist")
    st.write(f"Here are {len(matches)} options. Every member will pick their favourite next.")
    if len(matches) < 5:
        st.warning(
            f"Only {len(matches)} movies could be verified for these settings. "
            "The age-rating ceiling was not relaxed."
        )
    if st.session_state.relax_notes:
        st.caption("Search tried: " + " · ".join(st.session_state.relax_notes))
    for i, match in enumerate(matches, start=1):
        render_movie_card(match, i)
    if st.button("Start voting", type="primary", use_container_width=True):
        clear_vote_widget_state()
        st.session_state.member_picks = {}
        st.session_state.turn_index = 0
        st.session_state.verdict = None
        go("vote")
    if st.button("Back to members", use_container_width=True):
        go("members")


def format_movie_option(movie_id: int) -> str:
    for match in st.session_state.results:
        if match.movie_id == movie_id:
            return f"{match.title} ({match.year or '—'}) · ⭐ {match.vote_average:.1f}/10"
    return "Movie"


def page_vote() -> None:
    matches: list[MovieMatch] = st.session_state.results or []
    members: list[str] = st.session_state.members
    if not matches or not members:
        go("members")
        return
    if st.session_state.verdict is not None:
        go("verdict")
        return

    st.markdown("<div class='step-label'>STEP 4 OF 4</div>", unsafe_allow_html=True)
    st.title("Pass the phone")
    turn = st.session_state.turn_index
    if turn >= len(members):
        st.success("Everyone has voted. Ready to reveal the result?")
        picks = st.session_state.member_picks
        counts = {match.movie_id: 0 for match in matches}
        for movie_id in picks.values():
            if movie_id in counts:
                counts[movie_id] += 1
        for match in matches:
            st.caption(f"{match.title}: {counts[match.movie_id]} vote(s)")
        if st.button("Reveal the verdict", type="primary", use_container_width=True):
            high_score = max(counts.values()) if counts else 0
            tied = [match.movie_id for match in matches if counts[match.movie_id] == high_score]
            top_rated_id = max(
                tied,
                key=lambda mid: next(m.vote_average for m in matches if m.movie_id == mid),
            )
            st.session_state.verdict = {
                "counts": counts,
                "top_score": high_score,
                "tied_ids": tied,
                "winner_id": top_rated_id,
                "resolution": "rating",
            }
            go("verdict")
        return

    voter = members[turn]
    st.progress(turn / len(members), text=f"Voter {turn + 1} of {len(members)}")
    st.markdown(f"<div class='voter-card'><span>NOW VOTING</span><h2>{voter}</h2>Pick one movie below.</div>", unsafe_allow_html=True)
    options: list[int] = [match.movie_id for match in matches]
    selected = st.radio(
        "Which movie gets your vote?",
        options,
        index=0,  # First movie is selected unless the voter taps a different option.
        format_func=format_movie_option,
        key=f"turn_choice_{turn}",
    )
    if st.button("Save my pick and pass the phone", type="primary", use_container_width=True):
        selected_id = int(selected)
        st.session_state.member_picks[voter] = selected_id
        selected_match = next(m for m in matches if m.movie_id == selected_id)
        db.record_vote(st.session_state.night_id, selected_id, selected_match.title, "Selected", voter)
        st.session_state.turn_index += 1
        st.rerun()
    st.caption("Your pick is private until the group reveals the verdict. No take-backsies after passing the phone.")
    if st.button("Back to shortlist", use_container_width=True):
        go("results")


def page_verdict() -> None:
    matches: list[MovieMatch] = st.session_state.results or []
    verdict = st.session_state.verdict
    if not matches or not verdict:
        go("results")
        return
    if st.session_state.random_animation:
        st.balloons()
        st.snow()
        st.session_state.random_animation = False

    movie_map = {match.movie_id: match for match in matches}
    tied_ids = verdict["tied_ids"]
    winner = movie_map[verdict["winner_id"]]
    is_tie = len(tied_ids) > 1
    st.markdown("<div class='step-label'>THE FINAL VERDICT</div>", unsafe_allow_html=True)
    if is_tie:
        tied_movies = [movie_map[mid] for mid in tied_ids]
        if verdict["resolution"] == "random":
            st.title("The tie-breaker picked…")
            st.write(
                f"The top movies each received {verdict['top_score']} vote(s). "
                "The winner below was chosen at random from the tied movies."
            )
        else:
            st.title("It's a tie!")
            st.write(
                f"These movies each received {verdict['top_score']} vote(s). "
                "Our tiebreaker recommendation is the highest-rated one on TMDB."
            )
        st.markdown("**The tied movies**")
        for match in tied_movies:
            marker = "  ← recommended by rating" if match.movie_id == max(
                tied_ids, key=lambda mid: movie_map[mid].vote_average
            ) else ""
            st.write(f"• {match.title} · ⭐ {match.vote_average:.1f}/10 · {verdict['counts'][match.movie_id]} vote(s){marker}")
    else:
        st.title("Movie night has a winner")
        st.write(f"{winner.title} received the most votes, with {verdict['top_score']} vote(s).")

    left, right = st.columns([0.9, 2.1], gap="medium")
    with left:
        poster = tmdb_client.poster_url(winner.poster_path)
        if poster:
            st.image(poster, width=150)
        else:
            st.image(str(LOGO_PATH), width=120)
    with right:
        st.markdown(f"<div class='winner-label'>TONIGHT'S PICK</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='winner-title'>{winner.title}</div>", unsafe_allow_html=True)
        st.markdown(f"⭐ **{winner.vote_average:.1f}/10 on TMDB**", unsafe_allow_html=True)
        facts = [winner.year or "Year unknown", winner.runtime_text]
        if winner.certification:
            facts.append(winner.certification)
        st.caption(" · ".join(facts))
        genre_text = get_genre_label(winner.genre_ids)
        if genre_text:
            st.caption(genre_text)
        if winner.providers:
            st.caption("Streaming on: " + ", ".join(winner.providers[:4]))
        if winner.overview:
            st.write(winner.overview)

    if is_tie:
        if st.button("Randomize the winner", use_container_width=True):
            new_winner_id = random.choice(tied_ids)
            updated = dict(st.session_state.verdict)
            updated["winner_id"] = new_winner_id
            updated["resolution"] = "random"
            st.session_state.verdict = updated
            st.session_state.random_animation = True
            st.rerun()
    if st.button("Start another movie night", type="primary", use_container_width=True):
        reset_everything()

    st.caption("Movie information and ratings supplied by TMDB.")


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; --primary-color: #ff8a35; }
        html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
          background-color: #101114 !important; color: #f4f4f5 !important;
        }
        html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * {
          font-family: "Century Gothic", "CenturyGothic", AppleGothic, sans-serif !important;
        }
        /* Set readable foregrounds on every common Streamlit text surface. */
        .stApp, .stApp p, .stApp li, .stApp label, .stApp legend,
        .stApp [data-testid="stWidgetLabel"], .stApp [data-testid="stWidgetLabel"] p,
        .stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stMarkdownContainer"] p,
        .stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stText"],
        .stApp [data-testid="stRadio"] label, .stApp [data-testid="stCheckbox"] label,
        .stApp [data-testid="stExpander"] summary {
          color: #f0f0f3;
        }
        .stApp [data-testid="stCaptionContainer"] { color: #bcbcc5 !important; }
        .stApp [data-testid="stCaptionContainer"] p { color: #bcbcc5 !important; }
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 { color: #fafafa !important; }
        [data-testid="stMetric"] {
          background: #1b1c22; border: 1px solid #34343a; border-radius: 14px;
          padding: .75rem .8rem; min-height: 100px;
        }
        [data-testid="stMetricLabel"] { color: #d4d4da !important; }
        [data-testid="stMetricValue"] { color: #ff8a35 !important; }
        [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
        #MainMenu, footer { visibility: hidden; }
        .block-container { max-width: 760px; padding-top: 1.3rem; padding-bottom: 3rem; }
        h1, h2, h3 { letter-spacing: -0.035em; }
        h1 { line-height: 1.08; }
        .hero-kicker, .step-label, .winner-label { color: #ff8a35 !important; font-weight: 800; letter-spacing: .14em; font-size: .72rem; }
        .hero-kicker { margin-bottom: .45rem; }
        .brand-wordmark { color:#f4f4f5; font-size:.78rem; font-weight:900; letter-spacing:.16em; }
        .hero-panel { display:flex; align-items:center; gap:1rem; background:linear-gradient(120deg,#2a201a,#201c1a); border:1px solid #54321e; padding:1rem 1.15rem; border-radius:18px; margin:.8rem 0 1.1rem; }
        .hero-number { color:#ff8a35; font-size:3rem; line-height:1; font-weight:900; }
        .hero-panel span { color:#d0cfd4; font-size:.9rem; }
        .voter-card { padding:1rem 1.1rem; margin:.8rem 0 1rem; border:1px solid #54321e; border-radius:18px; background:#211d1b; }
        .voter-card span { color:#ff8a35; font-weight:800; font-size:.7rem; letter-spacing:.14em; }
        .voter-card h2 { margin:.2rem 0; }
        .member-row { padding:.65rem .8rem; border:1px solid #34343a; border-radius:12px; margin-bottom:.45rem; background:#1c1d22; color:#f4f4f5; overflow-wrap:anywhere; }
        .winner-title { color:#fff; font-size:1.55rem; font-weight:900; line-height:1.1; margin:.2rem 0 .5rem; overflow-wrap:anywhere; }

        /* Selectboxes and multiselect dropdowns: dark surface, light text, orange focus. */
        .stApp [data-baseweb="select"] > div {
          background-color: #22242b !important; color: #f4f4f5 !important;
          border-color: #555761 !important; border-radius: 10px !important;
        }
        .stApp [data-baseweb="select"] input,
        .stApp [data-baseweb="select"] [data-testid="stMarkdownContainer"],
        .stApp [data-baseweb="select"] span,
        .stApp [data-baseweb="select"] div { color: #f4f4f5 !important; }
        .stApp [data-baseweb="select"] svg { fill: #ff8a35 !important; color: #ff8a35 !important; }
        .stApp [data-baseweb="popover"], .stApp [data-baseweb="menu"],
        .stApp ul[role="listbox"], .stApp div[role="listbox"] {
          background-color: #202127 !important; border-color: #4a4c55 !important;
          color: #f4f4f5 !important;
        }
        .stApp [role="option"], .stApp li[role="option"],
        .stApp [data-baseweb="menu"] li {
          background-color: #202127 !important; color: #f4f4f5 !important;
        }
        .stApp [role="option"]:hover, .stApp [role="option"][aria-selected="true"],
        .stApp [data-baseweb="menu"] li:hover {
          background-color: #49301f !important; color: #ffffff !important;
        }
        .stApp [data-baseweb="tag"] { background-color: #4a2d1c !important; color: #ffffff !important; }
        .stApp [data-baseweb="tag"] *, .stApp [data-baseweb="tag"] svg { color: #ffffff !important; fill: #ffffff !important; }

        /* Text-entry widgets are dark too. */
        .stApp [data-baseweb="input"] > div, .stApp [data-baseweb="textarea"] > div,
        .stApp input, .stApp textarea {
          background-color: #22242b !important; color: #f4f4f5 !important;
          border-color: #555761 !important; caret-color: #ff8a35 !important;
        }
        .stApp input::placeholder, .stApp textarea::placeholder { color: #b4b5be !important; opacity: 1; }
        .stApp [data-baseweb="input"] svg { fill: #ff8a35 !important; }

        /* Neutral actions are charcoal; primary actions are orange with near-black text. */
        .stApp div.stButton > button,
        .stApp div[data-testid="stFormSubmitButton"] > button {
          min-height: 2.75rem; border-radius: 12px; font-weight: 700;
          background: #25272e !important; color: #f7f7f9 !important;
          border: 1px solid #50525c !important;
          transition: transform .12s ease, border-color .12s ease, background-color .12s ease;
        }
        .stApp div.stButton > button *,
        .stApp div[data-testid="stFormSubmitButton"] > button * { color: #f7f7f9 !important; }
        .stApp div.stButton > button:hover,
        .stApp div[data-testid="stFormSubmitButton"] > button:hover {
          border-color: #ff8a35 !important; background: #33343c !important;
          color: #ffffff !important; transform: translateY(-1px);
        }
        .stApp div.stButton > button[kind="primary"],
        .stApp div[data-testid="stFormSubmitButton"] > button[kind="primary"],
        .stApp button[data-testid="baseButton-primary"] {
          background: #ff8a35 !important; border-color: #ff8a35 !important;
          color: #17120f !important; font-weight: 800 !important;
        }
        .stApp div.stButton > button[kind="primary"] *,
        .stApp div[data-testid="stFormSubmitButton"] > button[kind="primary"] *,
        .stApp button[data-testid="baseButton-primary"] * { color: #17120f !important; }
        .stApp div.stButton > button[kind="primary"]:hover,
        .stApp div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover,
        .stApp button[data-testid="baseButton-primary"]:hover {
          background: #ffa05b !important; color: #17120f !important;
        }
        .stApp div[data-testid="stRadio"] label { border-radius: 10px; color: #f4f4f5 !important; }
        .stApp div[data-testid="stProgress"] > div > div { background-color:#ff8a35; }
        .stApp [data-testid="stAlert"] { color: #f4f4f5 !important; }
        @media (max-width: 640px) {
          .block-container { padding-left:1rem; padding-right:1rem; padding-top:1rem; }
          .hero-number { font-size:2.6rem; }
          .winner-title { font-size:1.35rem; }
          [data-testid="stMetric"] { padding:.65rem; min-height:92px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Use a small pre-sized copy of the brand mark as the button background.
    # This avoids relying on an image-button widget that Streamlit does not have.
    if LOGO_BUTTON_PATH.exists():
        logo_data = base64.b64encode(LOGO_BUTTON_PATH.read_bytes()).decode("ascii")
        st.markdown(
            f"""
            <style>
            .stApp .st-key-global_logo_home_button [data-testid="stButton"] > button,
            .stApp .st-key-global_logo_home_button div.stButton > button {{
              width:64px !important; min-width:64px !important;
              height:64px !important; min-height:64px !important;
              padding:0 !important; margin:0 !important;
              background-color:#101114 !important;
              background-image:url("data:image/png;base64,{logo_data}") !important;
              background-position:center !important; background-repeat:no-repeat !important;
              background-size:cover !important;
              border:1px solid #54321e !important; border-radius:16px !important;
              color:transparent !important; font-size:0 !important;
              box-shadow:none !important;
            }}
            .stApp .st-key-global_logo_home_button button p,
            .stApp .st-key-global_logo_home_button button span {{
              color:transparent !important; font-size:0 !important;
              line-height:0 !important; visibility:hidden !important;
            }}
            .stApp .st-key-global_logo_home_button button:hover {{
              border-color:#ff8a35 !important; transform:translateY(-1px);
            }}
            .stApp .st-key-global_logo_home_button button:focus-visible {{
              outline:2px solid #ff8a35 !important; outline-offset:3px !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )


def main() -> None:
    db.init_db()
    init_session()
    inject_style()
    render_top_nav()
    pages = {
        "home": page_home,
        "preferences": page_preferences,
        "members": page_members,
        "results": page_results,
        "vote": page_vote,
        "verdict": page_verdict,
    }
    pages.get(st.session_state.page, page_home)()


main()
