# Couch Verdict

The family movie filter. Pick who's watching, the vibe and your time limit, and Couch Verdict shortlists exactly 5 movies everyone can watch. Then the family votes. Built for Eureka, team EJ26T710899.

## Features
- Log in / create account (salted PBKDF2 password hashes, SQLite)
- Live statistics on the startup page (refreshes every 5 seconds)
- Always 5 movies. If strict filters leave fewer, the time limit, streaming services and genres relax in that order. The age rating never relaxes.
- Live, expansive movie data from [TMDB](https://www.themoviedb.org/) (age rating, runtime, genre and streaming service filters). Without a key it runs on a small demo catalogue.

## Run locally
```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then paste your free TMDB API key
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Push this folder to a GitHub repo.
2. At share.streamlit.io choose New app, pick the repo, set the main file to `app.py`.
3. Under Advanced settings, Secrets, add `TMDB_API_KEY = "your-key"`.

Note: Streamlit Cloud resets local files when the app restarts, so accounts and stats in the SQLite file reset too. For permanent data, point `_q` in `engine.py` at a hosted database such as Supabase.
