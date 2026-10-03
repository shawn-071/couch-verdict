import html
import os

import pandas as pd
import requests
import streamlit as st

import engine as E

st.set_page_config(page_title="Couch Verdict", page_icon="🛋️", layout="wide")
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,700;9..144,900&display=swap');
h1, h2, h3 {font-family: 'Fraunces', Georgia, serif !important; letter-spacing: -0.01em;}
.ticket {border: 1px dashed #f2b84b88; border-left: 6px solid #f2b84b; border-radius: 3px;
         padding: .55rem .75rem; margin: .35rem 0 .5rem;}
.ticket small {opacity: .8;}
</style>""",
    unsafe_allow_html=True,
)


def tmdb_key():
    try:
        return st.secrets["TMDB_API_KEY"]
    except Exception:
        return os.environ.get("TMDB_API_KEY")


@st.fragment(run_every=5)
def live_stats():
    s = E.stats()
    a, b, c, d = st.columns(4)
    a.metric("Families signed up", s["users"])
    b.metric("Shortlists made", s["lists"])
    c.metric("Last 24 hours", s["today"])
    d.metric("Scrolling saved (est.)", f"{s['saved']} min")
    if s["genres"]:
        st.caption("Genres families are picking. Updates every 5 seconds.")
        st.bar_chart(pd.Series(dict(s["genres"].most_common(8))), horizontal=True)
    else:
        st.caption("No shortlists yet. The first one starts this chart.")


def survey_strip():
    st.caption("Why it exists: our survey of 34 people")
    a, b, c = st.columns(3)
    a.metric("Juggle 2-3 streaming apps", "79.4%")
    b.metric("Spend 10-20 min choosing", "50%")
    c.metric("Want a shared filter", "64.7%")


def auth_view():
    tab_in, tab_up = st.tabs(["Log in", "Create account"])
    for tab, label, fn in ((tab_in, "Log in", E.login), (tab_up, "Create account", E.register)):
        with tab, st.form(label):
            name = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button(label, type="primary"):
                user, err = fn(name, pw)
                if user:
                    st.session_state.user = user
                    st.rerun()
                st.error(err)


def vote(movie_id):
    st.session_state.votes[movie_id] += 1


def picker_view(key):
    user = st.session_state.user
    with st.sidebar:
        st.markdown(f"Signed in as **{html.escape(user['name'])}**")
        platforms = st.multiselect("Our streaming services", list(E.PLATFORMS), disabled=not key,
                                   default=["Netflix"] if key else [])
        region = st.text_input("Country code", "US", max_chars=2, disabled=not key).strip().upper()
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
        st.caption("Movies come from the live TMDB database." if key else
                   f"Demo catalogue of {len(E.DEMO)} movies. Add a TMDB key to go live.")

    st.subheader("Tonight's brief")
    c1, c2, c3 = st.columns(3)
    labels = {"G": "G: little kids", "PG": "PG: kids", "PG-13": "PG-13: teens", "R": "R: adults only"}
    rating = c1.select_slider("Who's watching? (highest age rating)", E.RATINGS, value="PG",
                              format_func=labels.get)
    genres = c2.multiselect("What's the vibe? (pick up to 3)", list(E.GENRES), default=["Comedy"],
                            max_selections=3)
    mins = c3.slider("How much time do we have? (minutes)", 80, 200, 120, step=5)

    if st.button("Get our 5", type="primary", disabled=not genres):
        src = "tmdb" if key else "demo"
        with st.spinner("Checking every library..."):
            try:
                picks = E.recommend(key, genres, rating, mins, platforms, region)
            except requests.RequestException:
                src = "demo"
                st.warning("The live database wasn't reachable (check your TMDB key), so these come from the demo catalogue.")
                picks = E.recommend(None, genres, rating, mins, platforms, region)
        E.log_list(user["id"], genres, rating, mins, src)
        st.session_state.picks = picks
        st.session_state.votes = {m["id"]: 0 for m in picks}

    picks = st.session_state.get("picks")
    if not picks:
        st.info("Set who's watching, the vibe and your time limit, then press Get our 5.")
        return
    votes = st.session_state.votes
    st.subheader("Your five. Vote for one.")
    for col, m in zip(st.columns(5), picks):
        with col:
            if m["poster"]:
                st.image(m["poster"], use_container_width=True)
            meta = ", ".join(x for x in (m["rating"], f"{m['runtime']} min" if m["runtime"] else "",
                                         f"{m['score']}/10" if m["score"] else "") if x)
            st.markdown(
                f"<div class='ticket'><b>{html.escape(m['title'])}</b> ({m['year']})<br>"
                f"<small>{html.escape(meta)}<br>{html.escape(', '.join(m['genres']))}</small></div>",
                unsafe_allow_html=True)
            if m["overview"]:
                st.caption(m["overview"][:120] + "...")
            if m["providers"]:
                st.caption("Streaming on " + ", ".join(m["providers"]))
            if m["note"]:
                st.caption(f"Added from {m['note']}.")
            st.button("Vote", key=f"vote{m['id']}", on_click=vote, args=(m["id"],), use_container_width=True)
            st.caption(f"{votes[m['id']]} votes")
    top = max(votes.values())
    if top:
        winners = [m["title"] for m in picks if votes[m["id"]] == top]
        if len(winners) == 1:
            st.success(f"The verdict: {winners[0]}. Enjoy the movie.")
        else:
            st.warning("Tied: " + " and ".join(winners) + ". Vote again to break it.")


st.title("🛋️ Couch Verdict")
st.caption("Five movies everyone can watch, shortlisted in under two minutes.")
if st.session_state.get("user"):
    tab_pick, tab_stats = st.tabs(["Tonight's picks", "Live stats"])
    with tab_pick:
        picker_view(tmdb_key())
    with tab_stats:
        live_stats()
else:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Happening now")
        live_stats()
        survey_strip()
    with right:
        st.subheader("Start your movie night")
        auth_view()
