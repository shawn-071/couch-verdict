# Couch Verdict V.5.0

A simple, mobile-first movie-night picker with a dark navy and orange theme. Choose shared preferences, add the people in the room, review a five-movie shortlist, then pass one phone around so everyone can vote once.


## V.5.0 changes

- Country/region choices are loaded dynamically from TMDB's supported streaming-provider regions, instead of a short hard-coded country list.
- Movie-language choices are loaded dynamically from TMDB's configuration language list, including every ISO 639-1 language currently listed there.
- Replaced the audience-group preset with a multi-select **Age rating** filter. Rating choices come from TMDB's movie certification list for the selected region; “Any rating” is the default and must be selected by itself. Specific ratings can be combined, and movies must have a matching certification for that region.
- Changing country/region resets age-rating selections because each country can use a different certification scheme.

## How it works

1. Choose a streaming country/region, services, age ratings, genres, maximum movie length (kept as a strict limit), release decades, and language. Choose “Any rating” by itself or select one or more region-specific ratings. You must also explicitly select “Any decade” or at least one decade; “Any decade” cannot be combined with specific decades.
2. Add the names of everyone voting.
3. Review the movie shortlist found using TMDB.
4. Each person gets a preselected first movie and can tap another option, then passes the phone to the next person.
5. The movie with the most picks wins. If there is a tie, the app recommends the highest-rated tied movie on TMDB; the group can randomize the winner with an animation.

There is no account or sidebar. The home page shows fictional, continuously updating movie-indecision counters. These are simulated estimates, not analytics, and refresh every 3 seconds.

## Branding and theme

- `.streamlit/config.toml` explicitly sets the dark palette and orange accent.
- The latest logo in `assets/couch-verdict-logo.png` is used in the top-left home button, home page, poster fallbacks, and browser tab icon.
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

Movie information, posters, language options, region options, certification lists, and streaming availability come from [TMDB](https://www.themoviedb.org). Region options reflect the countries/regions for which TMDB lists streaming-provider data. Certification choices follow TMDB’s movie certification list for the selected region. Some regions may not have a separate certification list in TMDB; in those cases only “Any rating” is available.

The local SQLite database is not permanent storage on Streamlit Community Cloud; its contents may reset when the app container restarts.

## Updating an existing deployment

Replace the matching files in the repository root with the files from the ZIP, including both `app.py` and the entire `services/` folder. These files are version-coupled: `app.py` calls `find_five_movies(..., release_decades=...)`, so leaving an older `services/recommender.py` in place causes an unexpected-keyword error. Do not upload the ZIP itself as a single file, and do not nest the contents under an extra folder.


### V.4.3 compatibility fix

The top-left logo navigation uses Streamlit's supported `st.button` widget styled with the bundled logo image. Streamlit does not expose an `st.image_button` widget, so this avoids the `AttributeError` seen in deployment. The regular button remains keyboard-focusable and routes to Home when clicked.


### V.4.4 layout update

The Release decades multiselect is placed directly beneath the genre selector, inside the same bordered preferences card as the other filters. The selection validation and recommendation behavior are unchanged.

### V.5.0 region, language, and rating update

The preferences page retrieves supported regions, language codes, and movie certification definitions from TMDB's configuration endpoints. Age-rating filtering is applied against each movie's release-date certification for the chosen region. If specific ratings are selected, movies with missing or non-matching regional certifications are excluded; selecting “Any rating” leaves that filter unrestricted.


## Age-rating fallback (V.5.1)

When TMDB has no certification catalogue for the selected streaming region, Couch Verdict uses US movie certifications as the age-rating fallback. Streaming availability remains tied to the selected region. If specific ratings are selected, the app checks each movie's US certification; movies without a known US certification are excluded. This fallback is not a claim that US ratings are the local country's official ratings.
