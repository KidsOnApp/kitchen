"""One-off probe: which concert sites can be read, and do they carry schema.org Event data?"""
import json, re, urllib.request, html
URLS = [
  "https://www.bluenotemilano.com/",
  "https://www.bluenotemilano.com/programmazione/",
  "https://www.bluenotemilano.com/eventi/",
  "https://www.jazzmi.it/",
  "https://www.jazzmi.it/programma/",
  "https://www.torinojazzfestival.it/",
  "https://www.folkclub.it/concerti/",
  "https://ogrtorino.it/events",
  "https://www.jazzclub.torino.it/",
  "https://www.mentelocale.it/milano/eventi/concerti/",
  "https://www.mentelocale.it/torino/eventi/concerti/",
  "https://www.mentelocale.it/milano/eventi/",
  "https://www.songkick.com/metro-areas/30359-italy-milan",
  "https://www.songkick.com/metro-areas/30344-italy-turin",
  "https://www.bandsintown.com/c/milan-italy?genre_filter=Jazz",
  "https://www.ticketone.it/city/milano-217/",
  "https://www.vivaticket.com/it/ricerca?q=jazz",
  "https://www.ticketmaster.it/discover/milano",
  "https://www.allaboutjazz.com/calendar/",
  "https://musicbrainz.org/ws/2/artist/?query=artist:%22Brandee%20Younger%22&fmt=json&limit=1",
]
UA = "kitchen-tv-page/1.0 (personal, github.com/KidsOnApp/kitchen)"
def events_in(obj, out):
    if isinstance(obj, list):
        for x in obj: events_in(x, out)
    elif isinstance(obj, dict):
        t = obj.get("@type"); t = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.endswith("Event") for x in t):
            out.append({k: obj.get(k) for k in ("@type","name","startDate","location","performer","url")})
        for v in obj.values(): events_in(v, out)
report = []
for u in URLS:
    r = {"url": u}
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Language": "it,en"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read(3_000_000).decode("utf-8", "replace")
            r["status"] = resp.status; r["final"] = resp.url
        r["bytes"] = len(body)
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        r["title"] = html.unescape(m.group(1).strip())[:120] if m else None
        evs = []
        for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', body, re.S | re.I):
            try: events_in(json.loads(blk), evs)
            except Exception as e: pass
        r["jsonld_events"] = len(evs); r["events_sample"] = evs[:4]
        r["rss"] = re.findall(r'<link[^>]+(?:rss|atom)\+xml[^>]*>', body, re.I)[:3]
        r["ical"] = sorted(set(re.findall(r'href="([^"]+\.ics[^"]*)"', body)))[:3]
        links = re.findall(r'href="([^"#]+)"', body)
        r["links_sample"] = [l for l in dict.fromkeys(links) if re.search(r"event|concert|evento|show|programm|artist", l, re.I)][:25]
        if "musicbrainz" in u: r["body"] = body[:600]
        r["text_sample"] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S|re.I))))[:1500]
    except Exception as e:
        r["error"] = repr(e)[:300]
    report.append(r)
json.dump(report, open("tools/probe-result.json", "w"), ensure_ascii=False, indent=1)
