"""Couch Verdict: a simple, mobile-first group movie picker."""
from __future__ import annotations

import random
import streamlit as st

from services import db, recommender, tmdb_client
from services.recommender import AUDIENCE_CERT_CEILING, MovieMatch

st.set_page_config(
    page_title="Couch Verdict",
    page_icon="🍿",
    layout="centered",
    initial_sidebar_state="collapsed",
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
RUNTIME_OPTIONS = {"Any length": None, "Under 90 minutes": 90, "Under 2 hours": 120}
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
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def go(page: str) -> None:
    st.session_state.page = page
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
                st.markdown("<div class='poster-placeholder'>🍿</div>", unsafe_allow_html=True)
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


def page_home() -> None:
    st.markdown("<div class='hero-kicker'>MOVIE NIGHT, SORTED</div>", unsafe_allow_html=True)
    st.title("🍿 Couch Verdict")
    st.markdown(
        "Pick your preferences, add your people, then let the room settle on one movie. "
        "No accounts, no sidebar, no 40-minute scrolling expedition."
    )
    st.markdown(
        "<div class='hero-panel'><div class='hero-number'>5</div>"
        "<div><strong>movies to choose from</strong><br>"
        "<span>One shared shortlist. One final verdict.</span></div></div>",
        unsafe_allow_html=True,
    )
    st.write("")
    if st.button("Start a movie night  →", type="primary", use_container_width=True):
        go("preferences")
    st.caption("Movie information and ratings supplied by TMDB.")


def page_preferences() -> None:
    st.markdown("<div class='step-label'>STEP 1 OF 4</div>", unsafe_allow_html=True)
    st.title("Set the vibe")
    st.write("Choose the services and limits everyone can live with.")

    region_label = st.selectbox(
        "Where do you stream?", list(REGIONS.keys()),
        index=list(REGIONS.keys()).index("Qatar"),
    )
    try:
        with st.spinner("Loading streaming services and genres…"):
            providers = tmdb_client.get_providers(REGIONS[region_label])
            genres = tmdb_client.get_genres()
    except tmdb_client.TMDBConfigError as exc:
        st.error(str(exc))
        st.info("The app owner needs to add a TMDB API key in Streamlit app settings → Secrets.")
        return
    except tmdb_client.TMDBApiError as exc:
        st.error(f"TMDB could not load the preferences: {exc}")
        st.info("Check your connection, then refresh the app.")
        return

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
        audience_label = st.radio(
            "Who's watching?", list(AUDIENCES.keys()), index=1, horizontal=True
        )
        ceiling = AUDIENCE_CERT_CEILING[AUDIENCES[audience_label]]
        if ceiling:
            st.caption(f"Age-rating ceiling: {ceiling} or below. Unknown ratings are not treated as safe.")
        else:
            st.caption("No age-rating ceiling selected.")
        genre_names = sorted(genres.values())
        chosen_genres = st.multiselect(
            "Pick up to 3 genres", genre_names, max_selections=3,
            placeholder="Comedy, animation, sci-fi…",
        )
        c1, c2 = st.columns(2)
        with c1:
            runtime_label = st.selectbox("Time available", list(RUNTIME_OPTIONS.keys()))
        with c2:
            era_label = st.selectbox("Release year", list(ERA_OPTIONS.keys()))
        lang_label = st.selectbox("Movie language", list(LANGUAGE_OPTIONS.keys()))
        submitted = st.form_submit_button("Next: add members  →", type="primary", use_container_width=True)

    if submitted:
        if not chosen_services:
            st.error("Choose at least one streaming service.")
            return
        if not chosen_genres:
            st.error("Choose at least one genre.")
            return
        st.session_state.preferences = {
            "region": REGIONS[region_label],
            "region_label": region_label,
            "services": chosen_services,
            "audience": AUDIENCES[audience_label],
            "audience_label": audience_label,
            "genres": chosen_genres,
            "max_runtime": RUNTIME_OPTIONS[runtime_label],
            "min_year": ERA_OPTIONS[era_label],
            "language": LANGUAGE_OPTIONS[lang_label],
        }
        st.session_state.results = []
        st.session_state.verdict = None
        go("members")

    if st.button("← Back home", use_container_width=True):
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
        st.form_submit_button("＋ Add member", on_click=add_member_callback, use_container_width=True)

    if st.session_state.member_error:
        st.warning(st.session_state.member_error)
    if st.session_state.members:
        st.markdown(f"**On the list · {len(st.session_state.members)}**")
        for i, name in enumerate(list(st.session_state.members)):
            col_name, col_remove = st.columns([4, 1])
            with col_name:
                st.markdown(f"<div class='member-row'>👤 &nbsp; {name}</div>", unsafe_allow_html=True)
            with col_remove:
                st.button("Remove", key=f"remove_member_{i}", on_click=remove_member_callback, args=(i,))
    else:
        st.info("No members added yet. Add at least one person to continue.")

    st.write("")
    if st.button("Next: find our 5 movies  →", type="primary", use_container_width=True):
        if not st.session_state.members:
            st.warning("Add at least one member first.")
            return
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
                    cert_ceiling=AUDIENCE_CERT_CEILING[prefs["audience"]],
                    min_year=prefs["min_year"],
                    language=prefs["language"],
                )
            if not matches:
                st.error(
                    "TMDB couldn't find any movies verified for these settings. "
                    "Try a different service, genre, or time limit."
                )
                return
            db.record_recommendations(night_id, matches)
            st.session_state.night_id = night_id
            st.session_state.results = matches
            st.session_state.relax_notes = notes
            st.session_state.member_picks = {}
            st.session_state.turn_index = 0
            st.session_state.verdict = None
            clear_vote_widget_state()
            go("results")
        except tmdb_client.TMDBConfigError as exc:
            st.error(str(exc))
        except tmdb_client.TMDBApiError as exc:
            st.error(f"TMDB is not responding right now: {exc}")
        except Exception as exc:
            st.error(f"Something went wrong while finding movies: {exc}")

    if st.button("← Back to preferences", use_container_width=True):
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
    if st.button("Start voting  →", type="primary", use_container_width=True):
        clear_vote_widget_state()
        st.session_state.member_picks = {}
        st.session_state.turn_index = 0
        st.session_state.verdict = None
        go("vote")
    if st.button("← Back to members", use_container_width=True):
        go("members")


def format_movie_option(movie_id: int | str) -> str:
    if movie_id == "":
        return "Choose a movie…"
    for match in st.session_state.results:
        if match.movie_id == movie_id:
            return f"{match.title} ({match.year or '—'}) · ⭐ {match.vote_average:.1f}/10"
    return "Choose a movie…"


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
        if st.button("Reveal the verdict  ✨", type="primary", use_container_width=True):
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
    options: list[int | str] = [""] + [match.movie_id for match in matches]
    selected = st.radio(
        "Which movie gets your vote?",
        options,
        index=0,
        format_func=format_movie_option,
        key=f"turn_choice_{turn}",
    )
    if st.button("Save my pick & pass the phone  →", type="primary", use_container_width=True):
        if selected == "":
            st.warning("Choose a movie before passing the phone.")
            return
        selected_id = int(selected)
        st.session_state.member_picks[voter] = selected_id
        selected_match = next(m for m in matches if m.movie_id == selected_id)
        db.record_vote(st.session_state.night_id, selected_id, selected_match.title, "Selected", voter)
        st.session_state.turn_index += 1
        st.rerun()
    st.caption("Your pick is private until the group reveals the verdict. No take-backsies after passing the phone.")
    if st.button("← Back to shortlist", use_container_width=True):
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
            st.title("🎲 The tie-breaker picked…")
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
        st.title("🍿 Movie night has a winner")
        st.write(f"{winner.title} received the most votes, with {verdict['top_score']} vote(s).")

    left, right = st.columns([0.9, 2.1], gap="medium")
    with left:
        poster = tmdb_client.poster_url(winner.poster_path)
        if poster:
            st.image(poster, width=150)
        else:
            st.markdown("<div class='poster-placeholder'>🍿</div>", unsafe_allow_html=True)
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
        if st.button("Randomize the winner  🎲", use_container_width=True):
            new_winner_id = random.choice(tied_ids)
            updated = dict(st.session_state.verdict)
            updated["winner_id"] = new_winner_id
            updated["resolution"] = "random"
            st.session_state.verdict = updated
            st.session_state.random_animation = True
            st.rerun()
    if st.button("Start another movie night  ↺", type="primary", use_container_width=True):
        reset_everything()

    st.caption("Movie information and ratings supplied by TMDB.")


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
        #MainMenu, footer { visibility: hidden; }
        .block-container { max-width: 760px; padding-top: 1.3rem; padding-bottom: 3rem; }
        h1, h2, h3 { letter-spacing: -0.035em; }
        h1 { line-height: 1.08; }
        .hero-kicker, .step-label, .winner-label { color: #ff8a35; font-weight: 800; letter-spacing: .14em; font-size: .72rem; }
        .hero-kicker { margin-bottom: .45rem; }
        .hero-panel { display:flex; align-items:center; gap:1rem; background:linear-gradient(120deg,#2a201a,#201c1a); border:1px solid #54321e; padding:1rem 1.15rem; border-radius:18px; margin:.8rem 0 1.1rem; }
        .hero-number { color:#ff8a35; font-size:3rem; line-height:1; font-weight:900; }
        .hero-panel span { color:#b9b8bd; font-size:.9rem; }
        .voter-card { padding:1rem 1.1rem; margin:.8rem 0 1rem; border:1px solid #54321e; border-radius:18px; background:#211d1b; }
        .voter-card span { color:#ff8a35; font-weight:800; font-size:.7rem; letter-spacing:.14em; }
        .voter-card h2 { margin:.2rem 0; }
        .member-row { padding:.65rem .8rem; border:1px solid #34343a; border-radius:12px; margin-bottom:.45rem; background:#1c1d22; overflow-wrap:anywhere; }
        .poster-placeholder { height:150px; width:100px; display:flex; justify-content:center; align-items:center; border-radius:12px; background:#23242b; font-size:2rem; }
        .winner-title { font-size:1.55rem; font-weight:900; line-height:1.1; margin:.2rem 0 .5rem; overflow-wrap:anywhere; }
        div.stButton > button { min-height:2.75rem; border-radius:12px; font-weight:700; transition:transform .12s ease, border-color .12s ease; }
        div.stButton > button:hover { border-color:#ff8a35; transform:translateY(-1px); }
        div[data-testid="stFormSubmitButton"] > button { min-height:2.75rem; border-radius:12px; font-weight:800; }
        div[data-testid="stRadio"] label { border-radius:10px; }
        div[data-testid="stProgress"] > div > div { background-color:#ff8a35; }
        @media (max-width: 640px) {
          .block-container { padding-left:1rem; padding-right:1rem; padding-top:1rem; }
          .hero-number { font-size:2.6rem; }
          .winner-title { font-size:1.35rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    db.init_db()
    init_session()
    inject_style()
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
