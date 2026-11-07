"""
Upcoming jazz concerts in Milan and Turin by non-Italian artists, for the kitchen page.

Runs once a day on GitHub Actions (.github/workflows/concerts.yml) and writes concerts.json.
- Concerts: Songkick listings for each city (schema.org MusicEvent data in the page).
- Jazz: on Songkick's jazz page, at a jazz venue, or tagged jazz on MusicBrainz.
- Nationality: MusicBrainz artist country; Italian headliners are dropped.
Artist lookups are cached in tools/artists-cache.json so MusicBrainz is asked once per artist.
"""
import datetime as dt, json, os, re, time, urllib.error, urllib.parse, urllib.request

CITIES = [
    {"name": "Milano", "metro": "30338-italy-milan"},
    {"name": "Torino", "metro": "30383-italy-turin"},
]
GENRE = "jazz"
# Concerts at these places count as jazz whatever the artist's tags say
JAZZ_VENUES = ["blue note", "jazz", "folkclub", "folk club", "torino jazz"]
JAZZ_TAGS = ("jazz", "bebop", "hard bop", "bossa nova", "big band", "swing", "fusion")
ALL_PAGES = 6            # pages of the all-genres listing to read per city (about 50 concerts each)
DAYS_AHEAD = 120
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


def artist_info(name):
    """{"country": ISO code or "", "jazz": tagged jazz on MusicBrainz}"""
    key = name.strip().lower()
    if isinstance(cache.get(key), dict):
        return cache[key]
    q = urllib.parse.quote(f'artist:"{name}"')
    country, jazz = "", False
    try:
        body = None
        for attempt in range(4):                     # MusicBrainz answers 503 when asked too fast
            wait = 1.6 - (time.time() - last_mb[0])
            if wait > 0:
                time.sleep(wait)
            last_mb[0] = time.time()
            try:
                body, _ = get(f"https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=5")
                break
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == 3:
                    raise
                time.sleep(4 * (attempt + 1))
        for a in json.loads(body).get("artists", []):
            same = a.get("name", "").lower() == key or any(
                x.get("name", "").lower() == key for x in a.get("aliases", []) or [])
            if same and int(a.get("score", 0)) >= 90:
                country = a.get("country") or ""
                if not country:
                    area = (a.get("area") or {}).get("name", "")
                    country = "IT" if area in ("Italy", "Italia") else ""
                tags = [t.get("name", "").lower() for t in a.get("tags", []) or []]
                jazz = any(j in t for t in tags for j in JAZZ_TAGS)
                break
    except Exception as e:
        log["errors"].append(f"musicbrainz {name}: {e!r}"[:200])
        return {"country": "", "jazz": False}
    cache[key] = {"country": country, "jazz": jazz}
    return cache[key]


today = dt.date.today()
limit = today + dt.timedelta(days=DAYS_AHEAD)
seen, events = set(), []
for city in CITIES:
    m = city["metro"]
    sources = [(f"https://www.songkick.com/metro-areas/{m}/genre/{GENRE}", 3, True)]
    sources += [(f"https://www.songkick.com/metro-areas/{m}/{y}/genre/{GENRE}", 3, True) for y in (today.year, today.year + 1)]
    sources += [(f"https://www.songkick.com/metro-areas/{m}", ALL_PAGES, False)]
    for base, pages, jazz_page in sources:
        for page in range(1, pages + 1):
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
                if names and k in seen and jazz_page:
                    for e in events:
                        if (e["date"], e["artists"][0].lower(), e["venue"].lower()) == k:
                            e["jazz_page"] = True
                if not names or k in seen:
                    continue
                seen.add(k)
                events.append({"date": start, "time": str(ev.get("startDate", ""))[11:16],
                               "city": city["name"], "venue": venue, "artists": names[:3],
                               "url": ev.get("url", ""), "jazz_page": jazz_page})
            if len(evs) < 10:
                break

keep = []
for e in sorted(events, key=lambda x: (x["date"], x["time"])):
    head = e["artists"][0]
    jazz_venue = any(v in e["venue"].lower() for v in JAZZ_VENUES)
    if not (e["jazz_page"] or jazz_venue):
        info = artist_info(head)
        if not info["jazz"]:
            continue                                     # not jazz: skip quietly
    info = artist_info(head)
    if info["country"] == "IT":
        log["dropped"].append(f'{e["date"]} {head} ({e["city"]}, {e["venue"]})')
        continue
    e["country"] = info["country"]
    e.pop("jazz_page", None)
    keep.append(e)

out = {"updated": log["run"], "events": keep[:MAX_EVENTS]}
json.dump(out, open(os.path.join(ROOT, "concerts.json"), "w"), ensure_ascii=False, indent=1)
json.dump(cache, open(CACHE_FILE, "w"), ensure_ascii=False, indent=0, sort_keys=True)
log["kept"] = len(keep)
json.dump(log, open(os.path.join(HERE, "concerts-log.json"), "w"), ensure_ascii=False, indent=1)
print(f"kept {len(keep)}, dropped {len(log['dropped'])}")
