"""Couch Verdict engine: accounts, live stats, movie sources and the 5-movie shortlist."""
import hashlib
import hmac
import os
import random
import secrets
import sqlite3
import time
from collections import Counter

import requests

DB_PATH = os.environ.get("CV_DB", "couchverdict.db")
TMDB = "https://api.themoviedb.org/3"
RATINGS = ["G", "PG", "PG-13", "R"]
GENRES = {"Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35, "Crime": 80, "Drama": 18,
          "Family": 10751, "Fantasy": 14, "Horror": 27, "Mystery": 9648, "Romance": 10749,
          "Sci-Fi": 878, "Thriller": 53}
PLATFORMS = {"Netflix": 8, "Prime Video": 9, "Disney+": 337, "Apple TV+": 350, "Max": 1899,
             "Hulu": 15, "Paramount+": 531}
MINUTES_SAVED = 15  # survey: half of groups spend 10-20 minutes choosing

# Demo catalogue, used only when no TMDB key is set. Title|year|US rating|minutes|genres
_DEMO = """Toy Story|1995|G|81|Animation,Comedy,Family
Toy Story 2|1999|G|92|Animation,Comedy,Family,Adventure
Toy Story 3|2010|G|103|Animation,Comedy,Family,Adventure
Monsters, Inc.|2001|G|92|Animation,Comedy,Family,Fantasy
Cars|2006|G|117|Animation,Comedy,Family,Adventure
The Lion King|1994|G|88|Animation,Family,Drama,Adventure
Aladdin|1992|G|90|Animation,Family,Fantasy,Adventure,Romance
Beauty and the Beast|1991|G|84|Animation,Family,Fantasy,Romance
Finding Nemo|2003|G|100|Animation,Family,Adventure
The Incredibles|2004|PG|115|Animation,Action,Family
Shrek|2001|PG|90|Animation,Comedy,Fantasy,Family
Coco|2017|PG|105|Animation,Family,Fantasy
Spider-Man: Into the Spider-Verse|2018|PG|117|Animation,Action,Adventure,Sci-Fi
Back to the Future|1985|PG|116|Adventure,Comedy,Sci-Fi
Jurassic Park|1993|PG-13|127|Adventure,Sci-Fi,Thriller
The Princess Bride|1987|PG|98|Adventure,Fantasy,Comedy,Romance
Paddington 2|2017|PG|103|Family,Comedy,Adventure
WALL-E|2008|G|98|Animation,Sci-Fi,Family
Inside Out|2015|PG|95|Animation,Comedy,Family
Home Alone|1990|PG|103|Comedy,Family
Ghostbusters|1984|PG|105|Comedy,Fantasy,Sci-Fi
Raiders of the Lost Ark|1981|PG|115|Action,Adventure
Knives Out|2019|PG-13|130|Comedy,Crime,Mystery
The Martian|2015|PG-13|144|Sci-Fi,Drama,Adventure
Ratatouille|2007|G|111|Animation,Comedy,Family,Fantasy
Moana|2016|PG|107|Animation,Adventure,Family,Comedy
Zootopia|2016|PG|108|Animation,Comedy,Adventure,Family,Crime,Mystery
Mission: Impossible - Fallout|2018|PG-13|147|Action,Adventure,Thriller
Get Out|2017|R|104|Horror,Mystery,Thriller
The Dark Knight|2008|PG-13|152|Action,Crime,Drama,Thriller
Superbad|2007|R|113|Comedy
Interstellar|2014|PG-13|169|Adventure,Drama,Sci-Fi
Spirited Away|2001|PG|125|Animation,Family,Fantasy
Jumanji: Welcome to the Jungle|2017|PG-13|119|Action,Adventure,Comedy,Fantasy
Big Hero 6|2014|PG|102|Animation,Action,Family,Comedy,Adventure
Kung Fu Panda|2008|PG|92|Animation,Action,Adventure,Family,Comedy
E.T. the Extra-Terrestrial|1982|PG|115|Sci-Fi,Family,Adventure
Top Gun: Maverick|2022|PG-13|130|Action,Drama"""
DEMO = [{"id": i, "title": t, "year": y, "rating": r, "runtime": int(m), "genres": g.split(","),
         "overview": "", "poster": None, "score": None, "providers": []}
        for i, (t, y, r, m, g) in enumerate(row.split("|") for row in _DEMO.splitlines())]


# ---------- accounts and live stats (SQLite) ----------
def _q(sql, args=(), commit=False):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT UNIQUE, salt TEXT, pw TEXT);"
        "CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY, uid INTEGER, ts REAL, genres TEXT,"
        " rating TEXT, mins INTEGER, source TEXT);")
    try:
        cur = con.execute(sql, args)
        rows = cur.fetchall()
        if commit:
            con.commit()
        return rows, cur.lastrowid
    finally:
        con.close()


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def register(name, pw):
    name = name.strip().lower()
    if len(name) < 3 or len(pw) < 6:
        return None, "Use a username of 3+ characters and a password of 6+ characters."
    salt = secrets.token_hex(16)
    try:
        _, uid = _q("INSERT INTO users(name, salt, pw) VALUES(?,?,?)", (name, salt, _hash(pw, salt)), True)
    except sqlite3.IntegrityError:
        return None, "That username is taken. Try another."
    return {"id": uid, "name": name}, ""


def login(name, pw):
    rows, _ = _q("SELECT * FROM users WHERE name=?", (name.strip().lower(),))
    if rows and hmac.compare_digest(rows[0]["pw"], _hash(pw, rows[0]["salt"])):
        return {"id": rows[0]["id"], "name": rows[0]["name"]}, ""
    return None, "Wrong username or password."


def log_list(uid, genres, rating, mins, source):
    _q("INSERT INTO lists(uid, ts, genres, rating, mins, source) VALUES(?,?,?,?,?,?)",
       (uid, time.time(), ",".join(genres), rating, mins, source), True)


def stats():
    users = _q("SELECT COUNT(*) n FROM users")[0][0]["n"]
    lists = _q("SELECT ts, genres FROM lists")[0]
    genres = Counter(g for r in lists for g in r["genres"].split(",") if g)
    return {"users": users, "lists": len(lists), "saved": len(lists) * MINUTES_SAVED, "genres": genres,
            "today": sum(r["ts"] > time.time() - 86400 for r in lists)}


# ---------- movie sources and the shortlist ----------
def _tmdb_pool(key, genres, rating, mins, platforms, region):
    p = {"api_key": key, "sort_by": "vote_average.desc", "vote_count.gte": 1500, "include_adult": "false",
         "certification_country": "US", "certification.lte": rating, "with_runtime.gte": 60,
         "with_runtime.lte": mins, "with_genres": "|".join(str(GENRES[g]) for g in genres)}
    if platforms:
        p.update(with_watch_providers="|".join(str(PLATFORMS[x]) for x in platforms), watch_region=region)
    r = requests.get(f"{TMDB}/discover/movie", params=p, timeout=10)
    r.raise_for_status()
    return [{"id": m["id"]} for m in r.json()["results"][:20]]


def _tmdb_detail(key, mid, region):
    r = requests.get(f"{TMDB}/movie/{mid}", timeout=10,
                     params={"api_key": key, "append_to_response": "watch/providers,release_dates"})
    r.raise_for_status()
    d = r.json()
    prov = d.get("watch/providers", {}).get("results", {}).get(region, {}).get("flatrate", [])
    cert = next((x["certification"] for c in d.get("release_dates", {}).get("results", [])
                 if c["iso_3166_1"] == "US" for x in c["release_dates"] if x["certification"]), "")
    poster = d.get("poster_path")
    return {"id": mid, "title": d["title"], "year": (d.get("release_date") or "")[:4], "rating": cert,
            "runtime": d.get("runtime"), "genres": [g["name"] for g in d.get("genres", [])],
            "overview": d.get("overview", ""), "score": round(d.get("vote_average", 0), 1),
            "poster": f"https://image.tmdb.org/t/p/w342{poster}" if poster else None,
            "providers": [x["provider_name"] for x in prov]}


def recommend(key, genres, rating, mins, platforms, region):
    """Always returns 5 movies. Soft limits relax step by step; the age rating never does."""
    steps = [("", mins, platforms, genres),
             ("a little over your time limit", mins + 30, platforms, genres),
             ("outside your streaming services", mins + 30, [], genres),
             ("outside your chosen genres", mins + 30, [], list(GENRES)),
             ("outside your time limit", 999, [], list(GENRES))]
    picks, seen = [], set()
    for note, mn, pl, gn in steps:
        if key:
            pool = _tmdb_pool(key, gn, rating, mn, pl, region)
        else:
            cap = RATINGS.index(rating)
            pool = [m for m in DEMO if RATINGS.index(m["rating"]) <= cap and m["runtime"] <= mn
                    and set(m["genres"]) & set(gn)]
        pool = [m for m in pool if m["id"] not in seen]
        random.shuffle(pool)
        for m in pool[:5 - len(picks)]:
            seen.add(m["id"])
            picks.append({**m, "note": note})
        if len(picks) == 5:
            break
    if key:
        picks = [{**_tmdb_detail(key, m["id"], region), "note": m["note"]} for m in picks]
    return picks
