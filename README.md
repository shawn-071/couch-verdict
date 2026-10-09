# Couch Verdict V.4.0

A simple, mobile-first movie-night picker with a dark navy and orange theme. Choose shared preferences, add the people in the room, review a five-movie shortlist, then pass one phone around so everyone can vote once.

## How it works

1. Choose your streaming region, services, audience, genres, maximum movie length (kept as a strict limit), selected release decades, and language.
2. Add the names of everyone voting.
3. Review the movie shortlist found using TMDB.
4. Each person gets a preselected first movie and can tap another option, then passes the phone to the next person.
5. The movie with the most picks wins. If there is a tie, the app recommends the highest-rated tied movie on TMDB; the group can randomize the winner with an animation.

There is no account or sidebar. The home page shows fictional, continuously updating movie-indecision counters. These are simulated estimates, not analytics, and refresh every 3 seconds.

## Branding and theme

- `.streamlit/config.toml` explicitly sets the dark palette and orange accent.
- The logo in `assets/couch-verdict-logo.png` is used in the home page, poster fallbacks, and browser tab icon.
- CSS requests Century Gothic first, followed by platform-specific fallbacks. Century Gothic must be installed on the viewer's device for the exact typeface to render; otherwise the browser uses a fallback.

## Run locally

```bash
pip install -r requirements.txt
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and add your TMDB API key:

```toml
[tmdb]
api_key = "YOUR_TMDB_API_KEY"
```

Then run:

```bash
streamlit run app.py
```

For Streamlit Community Cloud, paste the same TOML block into the app's **Settings → Secrets**. Never commit a real API key to GitHub.

## Project structure

```text
couch-verdict/
├── app.py
├── requirements.txt
├── assets/
│   └── couch-verdict-logo.png
├── services/
│   ├── __init__.py
│   ├── db.py
│   ├── recommender.py
│   └── tmdb_client.py
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

Movie information, ratings, posters, and streaming availability come from [TMDB](https://www.themoviedb.org). Streaming availability depends on the selected region. US age ratings are used by the recommendation engine.

The local SQLite database is not permanent storage on Streamlit Community Cloud; its contents may reset when the app container restarts.
