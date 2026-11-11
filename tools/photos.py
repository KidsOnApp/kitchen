"""
Weather-themed background photos from Unsplash, for the kitchen page.

Runs on GitHub Actions (.github/workflows/concerts.yml) and writes photos.json:
  { "updated": ..., "themes": { "rain": [ {url, name, profile}, ... ], ... } }
The Unsplash key comes from the repository secret UNSPLASH_ACCESS_KEY and never reaches the page.

Unsplash rules followed here:
- photos are hotlinked from the URLs the API returns (images.unsplash.com);
- each photo that enters the set triggers the API "download" event once (it is then used as a background);
- the page shows "Foto: <photographer> / Unsplash".
The demo key allows 50 requests per hour, so each run stays under ~45.
"""
import datetime as dt, json, os, random, sys, urllib.parse, urllib.request

KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "photos.json")
STATE = os.path.join(HERE, "photos-state.json")     # which photos already sent the download event
APP = "kitchen_tv"                                   # utm source required by Unsplash for attribution links

# theme -> search; the keys match the page's photo themes
THEMES = {
    "day_clear":  "sunny landscape blue sky",
    "day_cloudy": "cloudy sky landscape",
    "sunrise":    "sunrise landscape",
    "sunset":     "sunset landscape",
    "night":      "night sky stars landscape",
    "rain":       "rain landscape",
    "snow":       "snowy landscape",
    "fog":        "foggy landscape",
    "storm":      "storm clouds landscape",
}
PER_THEME = 30
REFRESH_PER_RUN = 1       # themes re-searched each night, oldest first (only once the download events are caught up)
BUDGET = 45               # API calls per run (limit is 50/hour)

if not KEY:
    print("UNSPLASH_ACCESS_KEY not set: nothing to do")
    sys.exit(0)

calls = 0


def api(url):
    global calls
    calls += 1
    req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {KEY}", "Accept-Version": "v1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


out = load(OUT, {"themes": {}})
state = load(STATE, {"searched": {}, "pinged": [], "pending": []})
themes = out.setdefault("themes", {})
pinged = set(state.get("pinged", []))
pending = state.get("pending", [])          # [photo id, download_location] still to ping

# which themes to (re)search: missing ones first, then the oldest
missing = [t for t in THEMES if not themes.get(t)]
oldest = sorted((t for t in THEMES if t not in missing), key=lambda t: state["searched"].get(t, ""))
todo = missing if missing else ([] if pending else oldest[:REFRESH_PER_RUN])

for t in todo:
    if calls >= BUDGET:
        break
    q = urllib.parse.quote(THEMES[t])
    try:
        d = api(f"https://api.unsplash.com/search/photos?query={q}&per_page={PER_THEME}"
                f"&orientation=landscape&content_filter=high&order_by=relevant&page={random.randint(1, 3)}")
    except Exception as e:
        print(f"search {t}: {e!r}")
        continue
    photos = []
    for p in d.get("results", []):
        if p.get("width", 0) < 1600:
            continue
        raw = p["urls"]["raw"]
        photos.append({
            "id": p["id"],
            "url": raw + ("&" if "?" in raw else "?") + "w=1920&h=1080&fit=crop&q=80&auto=format",
            "name": (p.get("user") or {}).get("name", ""),
            "profile": ((p.get("user") or {}).get("links") or {}).get("html", "") + f"?utm_source={APP}&utm_medium=referral",
        })
        dl = (p.get("links") or {}).get("download_location")
        if dl and p["id"] not in pinged and all(x[0] != p["id"] for x in pending):
            pending.append([p["id"], dl])
    if photos:
        themes[t] = photos
        state["searched"][t] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    print(f"{t}: {len(photos)} photos")

# download events for photos now in use, within the remaining budget
in_use = {p["id"] for ps in themes.values() for p in ps}
pending = [x for x in pending if x[0] in in_use]
while pending and calls < BUDGET:
    pid, dl = pending.pop(0)
    try:
        api(dl)
        pinged.add(pid)
    except Exception as e:
        print(f"download event {pid}: {e!r}")
        pending.append([pid, dl])
        break

out["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=0)
state["pinged"] = sorted(pinged & in_use)
state["pending"] = pending
json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=0)
print(f"api calls {calls}, download events still pending {len(pending)}")
