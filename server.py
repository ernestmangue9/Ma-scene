import os
import time
import secrets
import unicodedata
from urllib.parse import urlencode, quote
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, redirect, request, jsonify, send_from_directory

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, static_folder="public")

PORT = int(os.environ.get("PORT", 3000))
DEEZER_APP_ID = os.environ.get("DEEZER_APP_ID", "")
DEEZER_APP_SECRET = os.environ.get("DEEZER_APP_SECRET", "")
REDIRECT_URI = os.environ.get("REDIRECT_URI", f"http://localhost:{PORT}/callback")
BANDSINTOWN_APP_ID = os.environ.get("BANDSINTOWN_APP_ID", "concert-alert")
USER_COUNTRY = os.environ.get("USER_COUNTRY", "France")
USER_CITY = os.environ.get("USER_CITY", "Paris")
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "")
SONGKICK_API_KEY = os.environ.get("SONGKICK_API_KEY", "")

user_sessions = {}
concert_cache = {}

FRENCH_MAJOR_VENUES = [
    "Stade de France", "Orange Velodrome", "La Defense Arena", "Accor Arena",
    "Zenith", "Le Zenith", "Adidas Arena", "Dock Pullman", "Paris La Defense Arena",
    "Le Dome de Paris", "La Seine Musicale", "Halle Tony Garnier", "LDLC Arena",
    "Arkea Arena", "Zenith de Paris", "Le Grand Rex", "Parc des Princes",
    "Groupama Stadium", "Parc OL", "Stade Pierre-Mauroy", "Matmut Atlantique",
    "Allianz Riviera", "Roazhon Park", "Fnac Live", "E.Leclerc", "Espace Fnac",
]


def normalize(s=""):
    s = str(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = "".join(c for c in s if c.isalnum() or c == " ")
    return s.strip()


def is_major_french_venue(venue_name, country):
    v = normalize(venue_name)
    c = normalize(country)
    if c and "france" in c:
        return True
    for vn in FRENCH_MAJOR_VENUES:
        n = normalize(vn)
        if n in v or v.split()[:2] and " ".join(v.split()[:2]) in n:
            return True
    return False


def artist_matches(name, event):
    n = normalize(name)
    en = normalize(event.get("name", ""))
    attractions = event.get("_embedded", {}).get("attractions", event.get("attractions", []))
    attrs = [normalize(a.get("name", "")) for a in attractions]

    if n in attrs:
        return True
    if en == n:
        return True
    if " " in n:
        parts = [p for p in n.split() if len(p) > 2]
        joined = " | ".join(attrs) + " | " + en
        return all(p in joined for p in parts)
    return any(n in a.split() for a in attrs)


# ─── DEEZER AUTH ───

@app.route("/login")
def login():
    params = urlencode({
        "app_id": DEEZER_APP_ID,
        "redirect_uri": REDIRECT_URI,
        "perms": "basic_access,playlist_access_library,email",
    })
    return redirect(f"https://connect.deezer.com/oauth/auth.php?{params}")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/?error=auth_denied")
    try:
        resp = requests.get(
            "https://connect.deezer.com/oauth/access_token.php",
            params={
                "app_id": DEEZER_APP_ID,
                "secret": DEEZER_APP_SECRET,
                "code": code,
            },
            timeout=10,
        )
        # Deezer returns URL-encoded string: access_token=...&expires=...
        data = dict(item.split("=") for item in resp.text.split("&") if "=" in item)
        access_token = data.get("access_token", "")
        if not access_token:
            return redirect("/?error=token_failed")
        user_sessions[access_token] = {"created": time.time()}
        return redirect(f"/?token={quote(access_token)}#authenticated")
    except Exception as e:
        print(f"Auth callback error: {e}")
        return redirect("/?error=token_failed")


# ─── DEEZER API HELPERS ───

def deezer_get(url, token, params=None):
    if params is None:
        params = {}
    params["access_token"] = token
    resp = requests.get(url, params=params, timeout=15)
    return resp.json()


# ─── API ROUTES ───

@app.route("/api/playlists")
def api_playlists():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "No token provided"}), 401
    try:
        data = deezer_get("https://api.deezer.com/user/me/playlists", token)
        playlists = []
        for p in data.get("data", []):
            playlists.append({
                "id": p["id"],
                "name": p["title"],
                "image": p.get("picture_big") or p.get("picture_medium") or p.get("picture"),
                "trackCount": p.get("nb_tracks", 0),
                "owner": p.get("creator", {}).get("name", ""),
            })
        return jsonify({"playlists": playlists})
    except Exception as e:
        print(f"Deezer error /api/playlists: {e}")
        return jsonify({"error": "Failed to fetch playlists"}), 500


@app.route("/api/my-artists")
def api_my_artists():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "No token"}), 401

    artist_map = {}

    def add_artist(artist_id, name, source):
        if not name:
            return
        key = str(artist_id) if artist_id else name
        if key not in artist_map:
            artist_map[key] = {"id": artist_id, "name": name, "sources": set()}
        artist_map[key]["sources"].add(source)

    # 1) Artists from playlists
    try:
        page = 0
        while True:
            data = deezer_get("https://api.deezer.com/user/me/playlists", token, {"limit": 50, "index": page * 50})
            playlists = data.get("data", [])
            if not playlists:
                break
            for pl in playlists:
                try:
                    t_page = 0
                    while True:
                        tr_data = deezer_get(f"https://api.deezer.com/playlist/{pl['id']}/tracks", token, {"limit": 100, "index": t_page * 100})
                        tracks = tr_data.get("data", [])
                        if not tracks:
                            break
                        for track in tracks:
                            for a in track.get("artist", []):
                                if isinstance(a, dict):
                                    add_artist(a.get("id"), a.get("name"), "playlist")
                                elif isinstance(a, str):
                                    add_artist(None, a, "playlist")
                        if not tr_data.get("next"):
                            break
                        t_page += 1
                except Exception as e:
                    print(f"Playlist tracks error for {pl.get('title')}: {e}")
            if not data.get("next"):
                break
            page += 1
    except Exception as e:
        print(f"Error fetching playlists: {e}")

    # 2) Favorite tracks (user's liked songs)
    try:
        f_page = 0
        while True:
            fav_data = deezer_get("https://api.deezer.com/user/me/tracks", token, {"limit": 50, "index": f_page * 50})
            favs = fav_data.get("data", [])
            if not favs:
                break
            for fav in favs:
                artist = fav.get("artist", {})
                if isinstance(artist, dict):
                    add_artist(artist.get("id"), artist.get("name"), "favorites")
            if not fav_data.get("next"):
                break
            f_page += 1
    except Exception as e:
        print(f"Error fetching favorites: {e}")

    # 3) Enrich with popularity (from artist page)
    for key, val in artist_map.items():
        if val["id"]:
            try:
                artist_data = deezer_get(f"https://api.deezer.com/artist/{val['id']}", token)
                val["popularity"] = artist_data.get("nb_fan", 0)
            except Exception:
                val["popularity"] = 0
        else:
            val["popularity"] = 0

    artists = [
        {
            "id": v["id"],
            "name": v["name"],
            "popularity": v.get("popularity", 0),
            "sources": list(v["sources"]),
        }
        for v in artist_map.values()
    ]
    artists.sort(key=lambda x: x.get("popularity", 0), reverse=True)

    return jsonify({"artists": artists})


# ─── CONCERT SEARCH ───

def search_ticketmaster(artist_name):
    if not TICKETMASTER_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params={
                "apikey": TICKETMASTER_API_KEY,
                "keyword": artist_name,
                "size": 50,
                "countryCode": "FR",
                "sort": "date,asc",
            },
            timeout=10,
        )
        events = resp.json().get("_embedded", {}).get("events", [])
        now = time.time()
        results = []
        for e in events:
            start = e.get("dates", {}).get("start", {})
            dt_str = start.get("dateTime") or start.get("localDate", "")
            if not dt_str:
                continue
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.timestamp() < now:
                    continue
            except Exception:
                continue
            if not artist_matches(artist_name, e):
                continue
            venues = e.get("_embedded", {}).get("venues", [])
            v = venues[0] if venues else {}
            attractions = e.get("_embedded", {}).get("attractions", [])
            results.append({
                "artist": artist_name,
                "date": dt_str,
                "venue": v.get("name", "Unknown venue"),
                "city": v.get("city", {}).get("name", ""),
                "country": v.get("country", {}).get("countryCode", ""),
                "region": v.get("state", {}).get("stateCode", ""),
                "latitude": v.get("location", {}).get("latitude"),
                "longitude": v.get("location", {}).get("longitude"),
                "ticketUrl": e.get("url", ""),
                "ticketType": "Ticketmaster" if e.get("promoter") else "",
                "lineup": [a.get("name", "") for a in attractions],
                "source": "Ticketmaster",
            })
        return results
    except Exception as e:
        print(f"Ticketmaster error for {artist_name}: {e}")
        return []


def search_bandsintown(artist_name):
    try:
        encoded = quote(artist_name)
        url = f"https://rest.bandsintown.com/artists/{encoded}/events?app_id={BANDSINTOWN_APP_ID}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if not isinstance(data, list):
            return []
        now = time.time()
        results = []
        for e in data:
            if not e.get("upcoming"):
                continue
            dt_str = e.get("datetime", "")
            if not dt_str:
                continue
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.timestamp() < now:
                    continue
            except Exception:
                continue
            lineup = e.get("lineup", [])
            if not artist_matches(artist_name, {"name": "", "attractions": [{"name": x} for x in lineup]}):
                continue
            venue = e.get("venue", {})
            results.append({
                "artist": artist_name,
                "date": dt_str,
                "venue": venue.get("name", "Unknown venue"),
                "city": venue.get("city", "Unknown"),
                "country": venue.get("country", "Unknown"),
                "region": venue.get("region", ""),
                "latitude": venue.get("latitude"),
                "longitude": venue.get("longitude"),
                "ticketUrl": e.get("url", ""),
                "ticketType": e.get("description", ""),
                "lineup": lineup,
                "source": "Bandsintown",
            })
        return results
    except Exception as e:
        print(f"Bandsintown error for {artist_name}: {e}")
        return []


def get_venue_capacity(venue_name, city):
    if not SONGKICK_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://www.songkick.com/api/3.0/search/venues.json",
            params={"apikey": SONGKICK_API_KEY, "query": f"{venue_name} {city}"},
            timeout=5,
        )
        venues = resp.json().get("resultsPage", {}).get("results", {}).get("venue", [])
        if venues:
            cap = venues[0].get("capacity")
            return cap if isinstance(cap, int) else None
    except Exception:
        pass
    return None


def search_concerts_for_artist(artist_name):
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_tm = executor.submit(search_ticketmaster, artist_name)
        f_bit = executor.submit(search_bandsintown, artist_name)
        tm = f_tm.result()
        bit = f_bit.result()

    combined = tm + bit

    seen = set()
    unique = []
    for c in combined:
        key = f"{c['date']}-{normalize(c['venue'])}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    count = 0
    for c in unique:
        if count >= 30:
            break
        if is_major_french_venue(c["venue"], c["country"]):
            c["capacity"] = get_venue_capacity(c["venue"], c["city"])
            count += 1

    for c in unique:
        c["isFrance"] = is_major_french_venue(c["venue"], c["country"])

    unique.sort(key=lambda x: (not x["isFrance"], x.get("date", "")))
    return unique


@app.route("/api/concerts")
def api_concerts():
    artists = request.args.get("artists", "")
    if not artists:
        return jsonify({"error": "No artists specified"}), 400

    artist_list = [a.strip() for a in artists.split(",") if a.strip()]
    all_concerts = []

    for artist in artist_list:
        cached = concert_cache.get(artist)
        if cached and time.time() - cached["timestamp"] < 1800:
            all_concerts.extend(cached["concerts"])
            continue
        concerts = search_concerts_for_artist(artist)
        concert_cache[artist] = {"concerts": concerts, "timestamp": time.time()}
        all_concerts.extend(concerts)

    all_concerts.sort(key=lambda x: x.get("date", ""))
    return jsonify({"concerts": all_concerts})


@app.route("/api/concerts/<path:artist>")
def api_concerts_single(artist):
    artist = requests.utils.unquote(artist)
    concerts = search_concerts_for_artist(artist)
    return jsonify({"concerts": concerts})


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "cacheSize": len(concert_cache),
        "uptime": time.process_time(),
    })


# ─── SERVE FRONTEND ───

@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    import os
    file_path = os.path.join("public", path)
    if os.path.isfile(file_path):
        return send_from_directory("public", path)
    return send_from_directory("public", "index.html")


if __name__ == "__main__":
    print(f"\nMa Scene running at http://localhost:{PORT}")
    print(f"Monitoring concerts in: {USER_CITY}, {USER_COUNTRY}")
    print(f"\n1. Go to http://localhost:{PORT}")
    print(f"2. Log in with Deezer")
    print(f"3. Watch your artists' next concerts!\n")
    app.run(host="0.0.0.0", port=PORT, debug=True)
