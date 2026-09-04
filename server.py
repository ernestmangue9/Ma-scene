import os
import time
import secrets
import base64
from urllib.parse import urlencode, quote
from functools import wraps

import requests
from flask import Flask, redirect, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="public")

PORT = int(os.environ.get("PORT", 3000))
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
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
    import unicodedata
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


# ─── SPOTIFY AUTH ───

@app.route("/login")
def login():
    state = secrets.token_hex(16)
    scope = "playlist-read-private playlist-read-collaborative user-read-private user-read-email user-top-read user-read-recently-played"
    params = urlencode({
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "scope": scope,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "show_dialog": "true",
    })
    return redirect(f"https://accounts.spotify.com/authorize?{params}")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/?error=auth_denied")
    try:
        auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10,
        )
        data = resp.json()
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 3600)
        state = request.args.get("state", "")
        user_sessions[state] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "created": time.time(),
        }
        return redirect(f"/?token={quote(access_token)}#authenticated")
    except Exception as e:
        print(f"Auth callback error: {e}")
        return redirect("/?error=token_failed")


# ─── API ROUTES ───

@app.route("/api/playlists")
def api_playlists():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "No token provided"}), 401
    try:
        playlists = []
        url = "https://api.spotify.com/v1/me/playlists?limit=50"
        while url:
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
            data = resp.json()
            items = data.get("items", [])
            for p in items:
                playlists.append({
                    "id": p["id"],
                    "name": p["name"],
                    "image": (p.get("images") or [{}])[0].get("url") if p.get("images") else None,
                    "trackCount": p.get("tracks", {}).get("total", 0),
                    "owner": p.get("owner", {}).get("display_name", ""),
                })
            url = data.get("next")
        return jsonify({"playlists": playlists})
    except Exception as e:
        print(f"Spotify error /api/playlists: {e}")
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
        key = artist_id or name
        if key not in artist_map:
            artist_map[key] = {"id": artist_id, "name": name, "sources": set()}
        artist_map[key]["sources"].add(source)

    # 1) Artists from playlists
    try:
        url = "https://api.spotify.com/v1/me/playlists?limit=50"
        while url:
            pl_res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
            playlists = pl_res.json().get("items", [])
            for pl in playlists:
                t_url = f"https://api.spotify.com/v1/playlists/{pl['id']}/tracks?limit=100"
                try:
                    while t_url:
                        tr_res = requests.get(t_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
                        for item in tr_res.json().get("items", []):
                            track = item.get("track")
                            if not track or not track.get("artists"):
                                continue
                            for a in track["artists"]:
                                add_artist(a.get("id"), a.get("name"), "playlist")
                        t_url = tr_res.json().get("next")
                except Exception as e:
                    print(f"Playlist tracks error for {pl.get('name')}: {e}")
            url = pl_res.json().get("next")
    except Exception as e:
        print(f"Error fetching playlists: {e}")

    # 2) Top artists
    top_artists = []
    try:
        top = requests.get(
            "https://api.spotify.com/v1/me/top/artists?limit=50&time_range=medium_term",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        top_artists = top.json().get("items", [])
        for a in top_artists:
            add_artist(a.get("id"), a.get("name"), "top")
    except Exception as e:
        print(f"Error fetching top artists: {e}")

    # 3) Enrich with popularity
    ids = [k for k in artist_map.keys() if k]
    pop_map = {}
    for a in top_artists:
        if a.get("popularity") is not None:
            pop_map[a["id"]] = a["popularity"]
    try:
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            lookup = requests.get(
                f"https://api.spotify.com/v1/artists?ids={','.join(batch)}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            for a in lookup.json().get("artists", []):
                if a and a.get("popularity") is not None:
                    pop_map[a["id"]] = a["popularity"]
    except Exception as e:
        print(f"Error fetching artist popularity: {e}")

    artists = [
        {
            "id": v["id"],
            "name": v["name"],
            "popularity": pop_map.get(v["id"], 0),
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
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
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
    print(f"2. Log in with Spotify")
    print(f"3. Watch your artists' next concerts!\n")
    app.run(host="0.0.0.0", port=PORT, debug=True)
