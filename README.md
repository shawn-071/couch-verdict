# 🍿 Couch Verdict

**Find a movie everyone can agree on — in under two minutes.**

Couch Verdict ends family movie-night decision paralysis. Pick the streaming
services you actually pay for, set your group's shared limits (who's watching,
genres, time available), and get exactly five movies that fit — then let the
group vote.

## Features

- **Shared-preference filter**: streaming services, audience age level
  (kids / mixed / adults), up to 3 genres, runtime cap, release year and
  language.
- **Always five movies**: a relaxation ladder keeps broadening the search
  (any of your genres → any length → top picks on your services) until five
  verified matches are found. Near-matches are labelled honestly, and the
  **age ceiling is never relaxed** — movies without a verified US rating are
  never shown as kid-safe.
- **Group voting**: everyone votes Watch this / Maybe / Pass; the majority
  pick becomes the verdict.
- **Live statistics** on the home page: movie nights, recommendations, votes,
  saved movies (activity for the current deployment instance).
- **Accounts with passwords**: create an account or sign in; voters just type their name.
- **Saved watchlist** per profile.

## Data & credits

Movie data and streaming availability come from
[TMDB](https://www.themoviedb.org). Age ratings shown are US theatrical
ratings (G / PG / PG-13). Streaming availability depends on the selected
region.

## Run locally

```bash
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` (copy the example) and add your TMDB API key:

```toml
[tmdb]
api_key = "YOUR_TMDB_API_KEY"
```

Then:

```bash
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app from
   the repo with `app.py` as the entry point.
3. In the app's **Settings → Secrets**, paste:

```toml
[tmdb]
api_key = "YOUR_TMDB_API_KEY"
```

4. Reboot the app. Done — no key ever touches GitHub.

## Project structure

```text
couch-verdict/
├── app.py                    # UI: home, preferences, results, vote, saved
├── requirements.txt
├── services/
│   ├── tmdb_client.py        # TMDB API calls (cached)
│   ├── recommender.py        # always-5 relaxation engine
│   └── db.py                 # SQLite stats, votes, watchlist
└── .streamlit/
    └── secrets.toml.example  # template; real secrets stay local/cloud-only
```

Note: the SQLite database lives in the app container, so stats reset if the
app restarts on Community Cloud.
