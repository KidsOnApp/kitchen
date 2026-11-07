"""
Upcoming jazz concerts in Milan and Turin by non-Italian artists, for the kitchen page.

Runs once a day on GitHub Actions (.github/workflows/concerts.yml) and writes concerts.json.
- Concerts: Songkick jazz pages for each city (schema.org MusicEvent data in the page).
- Nationality: MusicBrainz artist country; Italian headliners are dropped.
Artist lookups are cached in tools/artists-cache.json so MusicBrainz is asked once per artist.
"""
import datetime as dt, json, os, re, time, urllib.parse, urllib.request

CITIES = [
    {"name": "Milano", "metro": "30338-italy-milan"},
    {"name": "Torino", "metro": "30383-italy-turin"},
]
GENRE = "jazz"
DAYS_AHEAD = 90
MAX_EVENTS = 30
UA = "kitchen-tv-page/1.0 (personal page; https://github.com/KidsOnApp/kitchen)"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE_FILE = os.path.join(HERE, "artists-cache.json")
log = {"run": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "pages": [], "dropped": [], "errors": []}


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,it"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.url


def music_events(obj, out):
    if isinstance(obj, list):
        for x in obj:
            music_events(x, out)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        t = t if isinstance(t, list) else [t]
        if "MusicEvent" in t or "Event" in t:
            out.append(obj)
        else:
            for v in obj.values():
                music_events(v, out)


def page_events(url):
    body, final = get(url)
    evs = []
    for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', body, re.S | re.I):
        try:
            music_events(json.loads(blk), evs)
        except ValueError:
            pass
    return evs, final


def performers(ev):
    p = ev.get("performer") or []
    p = p if isinstance(p, list) else [p]
    names = [x.get("name") for x in p if isinstance(x, dict) and x.get("name")]
    if not names and ev.get("name"):
        names = [ev["name"].split(" @ ")[0].strip()]
    return names


try:
    cache = json.load(open(CACHE_FILE))
except (OSError, ValueError):
    cache = {}
last_mb = [0.0]


def country_of(name):
    """ISO country of the artist on MusicBrainz, '' if unknown."""
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    wait = 1.2 - (time.time() - last_mb[0])
    if wait > 0:
        time.sleep(wait)
    last_mb[0] = time.time()
    q = urllib.parse.quote(f'artist:"{name}"')
    country = ""
    try:
        body, _ = get(f"https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=5")
        for a in json.loads(body).get("artists", []):
            same = a.get("name", "").lower() == key or any(
                x.get("name", "").lower() == key for x in a.get("aliases", []) or [])
            if same and int(a.get("score", 0)) >= 90:
                country = a.get("country") or ""
                if not country:
                    area = (a.get("area") or {}).get("name", "")
                    country = "IT" if area in ("Italy", "Italia") else ""
                break
    except Exception as e:
        log["errors"].append(f"musicbrainz {name}: {e!r}"[:200])
        return ""
    cache[key] = country
    return country


today = dt.date.today()
limit = today + dt.timedelta(days=DAYS_AHEAD)
seen, events = set(), []
for city in CITIES:
    urls = [f"https://www.songkick.com/metro-areas/{city['metro']}/genre/{GENRE}"]
    urls += [f"https://www.songkick.com/metro-areas/{city['metro']}/{y}/genre/{GENRE}" for y in (today.year, today.year + 1)]
    for base in urls:
        for page in (1, 2, 3):
            url = base + (f"?page={page}" if page > 1 else "")
            try:
                evs, final = page_events(url)
            except Exception as e:
                log["pages"].append({"url": url, "error": repr(e)[:200]})
                break
            log["pages"].append({"url": url, "final": final, "events": len(evs)})
            if city["metro"].split("-")[0] not in final:      # redirected elsewhere: wrong page
                break
            for ev in evs:
                start = str(ev.get("startDate", ""))[:10]
                try:
                    day = dt.date.fromisoformat(start)
                except ValueError:
                    continue
                if not (today <= day <= limit):
                    continue
                names = performers(ev)
                loc = ev.get("location") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                venue = loc.get("name", "") if isinstance(loc, dict) else ""
                k = (start, (names or [""])[0].lower(), venue.lower())
                if not names or k in seen:
                    continue
                seen.add(k)
                events.append({"date": start, "time": str(ev.get("startDate", ""))[11:16],
                               "city": city["name"], "venue": venue, "artists": names[:3],
                               "url": ev.get("url", "")})
            if len(evs) < 10:
                break

keep = []
for e in sorted(events, key=lambda x: (x["date"], x["time"])):
    head = e["artists"][0]
    c = country_of(head)
    if c == "IT":
        log["dropped"].append(f'{e["date"]} {head} ({e["city"]})')
        continue
    e["country"] = c
    keep.append(e)

out = {"updated": log["run"], "events": keep[:MAX_EVENTS]}
json.dump(out, open(os.path.join(ROOT, "concerts.json"), "w"), ensure_ascii=False, indent=1)
json.dump(cache, open(CACHE_FILE, "w"), ensure_ascii=False, indent=0, sort_keys=True)
log["kept"] = len(keep)
json.dump(log, open(os.path.join(HERE, "concerts-log.json"), "w"), ensure_ascii=False, indent=1)
print(f"kept {len(keep)}, dropped {len(log['dropped'])}")
