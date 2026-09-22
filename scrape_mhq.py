#!/usr/bin/env python3
"""Scrape Warhammer 40k tournaments in France from miniheadquarters.com.

The site has no public API (server-rendered Django pages). Three listings share
the same layout: /tournaments/individual/, /tournaments/team/ and
/tournaments/side-by-side/ (2v2). Each accepts ?country=FR&game_system=1&page_size=48&page=N.
Cards give name, date, game and registrations (players for individual events,
teams otherwise). The detail page embeds a Leaflet marker with coordinates and
the address, plus status, rounds and team size. Detail pages are cached under
cache/mhq/<type>/ and re-fetched only for events that are not finished yet.
"""
import argparse, concurrent.futures as cf, datetime as dt, html, json, os, re, sys, time, urllib.parse, urllib.request

BASE = "https://miniheadquarters.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MONTHS = {"jan": 1, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
          "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
TYPES = {"individual": "solo", "team": "team", "side-by-side": "2v2"}


def fetch(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  ! {url}: {e} (retry in {wait}s)", file=sys.stderr)
            time.sleep(wait)
    return None


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_date(s):
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})", s.strip())
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower().rstrip("."))
    return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}" if mon else None


def parse_list(page_html, ttype):
    cards = []
    pat = r'<a href="(https://miniheadquarters\.com/tournaments/%s/details/[^"]+)"(.*?)</a>' % re.escape(ttype)
    for m in re.finditer(pat, page_html, flags=re.S):
        url, body = m.group(1), m.group(2)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", body, flags=re.S)
        fields = {clean(k): clean(v) for k, v in re.findall(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', body, flags=re.S)}
        badges = [clean(b) for b in re.findall(r'<span[^>]*rounded-full[^>]*>(.*?)</span>', body, flags=re.S)]
        reg = re.match(r"(\d+)\s*/\s*(\d+)", fields.get("Registrations", ""))
        cards.append({
            "type": ttype, "url": url, "slug": url.rsplit("/", 1)[-1],
            "name": clean(title.group(1)) if title else None,
            "date": parse_date(fields.get("Date", "")), "dateRaw": fields.get("Date"),
            "game": fields.get("Game"),
            "entries": int(reg.group(1)) if reg else None,
            "capacity": int(reg.group(2)) if reg else None,
            "interested": int(fields["Interested"]) if fields.get("Interested", "").isdigit() else None,
            "badges": [b for b in badges if b],
        })
    total = re.search(r"of\s+(\d+)\s+total", page_html)
    return cards, int(total.group(1)) if total else None


def parse_detail(page_html):
    d = {}
    m = re.search(r"L\.marker\(\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]\)\.addTo\(map\)\s*\.bindPopup\('(.*?)'\)", page_html, flags=re.S)
    if m:
        d["lat"], d["lon"], d["address"] = float(m.group(1)), float(m.group(2)), clean(m.group(3))
    st = re.search(r">\s*Status\s*</h2>\s*<span[^>]*>\s*(.*?)\s*</span>", page_html, flags=re.S)
    if st:
        d["status"] = clean(st.group(1))
    rd = re.search(r">\s*Rounds\s*</div>\s*<div[^>]*>(.*?)</div>", page_html, flags=re.S)
    if rd:
        d["roundsRaw"] = clean(rd.group(1))
        n = re.search(r"(\d+)", d["roundsRaw"])
        d["rounds"] = int(n.group(1)) if n else None
    ts = re.search(r">\s*Team size\s*</div>\s*<div[^>]*>(.*?)</div>", page_html, flags=re.S)
    if ts:
        n = re.search(r"(\d+)", clean(ts.group(1)))
        d["teamSize"] = int(n.group(1)) if n else None
    org = re.search(r">\s*Organizers\s*</h2>(.*?)</div>\s*</div>", page_html, flags=re.S)
    if org:
        names = [clean(x) for x in re.findall(r"<(?:a|span|p)[^>]*>(.*?)</(?:a|span|p)>", org.group(1), flags=re.S)]
        d["organizer"] = ", ".join(dict.fromkeys(n for n in names if n and n.lower() != "contact")) or None
    desc = re.search(r'<meta name="description" content="([^"]*)"', page_html)
    if desc:
        d["description"] = html.unescape(desc.group(1))[:600]
    else:
        det = re.search(r">\s*Details\s*</h2>(.*?)</div>", page_html, flags=re.S)
        if det:
            d["description"] = clean(det.group(1))[:600]
    m2 = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, flags=re.S)
    if m2:
        d["nameFull"] = clean(m2.group(1))
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", default="FR")
    ap.add_argument("--game", default="1", help="miniheadquarters game_system id (1 = Warhammer 40000)")
    ap.add_argument("--types", default="individual,team,side-by-side", help="comma-separated listing types")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true", help="re-fetch every detail page, even cached finished ones")
    ap.add_argument("--out", default="data/mhq.json")
    ap.add_argument("--cache", default="cache/mhq")
    a = ap.parse_args()
    types = [t.strip() for t in a.types.split(",") if t.strip() in TYPES]

    def list_url(ttype, page):
        return f"{BASE}/tournaments/{ttype}/?" + urllib.parse.urlencode({"country": a.country, "game_system": a.game, "page_size": 48, "page": page})

    cards = []
    for ttype in types:
        first = fetch(list_url(ttype, 1))
        if not first:
            raise SystemExit(f"cannot reach miniheadquarters ({ttype})")
        found, total = parse_list(first, ttype)
        pages = -(-total // 48) if total else 1
        print(f"[{ttype}] {total} tournaments, {pages} list pages", file=sys.stderr)
        for p in range(2, pages + 1):
            h = fetch(list_url(ttype, p))
            if h:
                more, _ = parse_list(h, ttype)
                found.extend(more)
                print(f"  [{ttype}] list page {p}/{pages}: {len(more)} cards", file=sys.stderr)
            time.sleep(0.3)
        cards.extend(found)
    by_key = {(c["type"], c["slug"]): c for c in cards}
    print(f"{len(by_key)} unique tournaments across {len(types)} listings", file=sys.stderr)

    today = dt.date.today().isoformat()

    def get_detail(card):
        folder = os.path.join(a.cache, card["type"])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, card["slug"] + ".json")
        if os.path.exists(path) and not a.refresh:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if (card["date"] or "") < today and (cached.get("status") == "Finished" or "lat" in cached):
                return cached
        h = fetch(card["url"])
        if not h:
            return {}
        d = parse_detail(h)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        time.sleep(0.2)
        return d

    out, done = [], 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(get_detail, c): c for c in by_key.values()}
        for fut in cf.as_completed(futs):
            c, d = futs[fut], fut.result()
            done += 1
            if done % 50 == 0:
                print(f"  details {done}/{len(futs)}", file=sys.stderr)
            addr = d.get("address") or ""
            zipm = re.search(r"\b(\d{5})\b", addr)
            city = None
            if zipm:
                tail = addr[zipm.end():].strip(" ,-")
                city = tail.split(",")[0].strip() or None
            fmt = TYPES[c["type"]]
            team_size = d.get("teamSize") or (2 if fmt == "2v2" else None)
            per_team = fmt == "solo"
            ident = f"mhq:{c['slug']}" if c["type"] == "individual" else f"mhq:{c['type']}:{c['slug']}"
            out.append({
                "source": "mhq", "id": ident, "name": d.get("nameFull") or c["name"], "url": c["url"],
                "game": c.get("game"), "date": c["date"], "endDate": None,
                "format": fmt, "teamSize": team_size, "teamEvent": fmt != "solo",
                "venue": None, "address": addr or None, "city": city, "region": None, "zip": zipm.group(1) if zipm else None,
                "country": "France" if a.country == "FR" else a.country,
                "lat": d.get("lat"), "lon": d.get("lon"),
                "players": c["entries"] if per_team else (c["entries"] * team_size if c["entries"] is not None and team_size else None),
                "capacity": c["capacity"] if per_team else (c["capacity"] * team_size if c["capacity"] is not None and team_size else None),
                "teams": None if per_team else c["entries"], "teamsCapacity": None if per_team else c["capacity"],
                "interested": c["interested"],
                "rounds": d.get("rounds"),
                "status": d.get("status"),
                "started": d.get("status") in ("Registrations closed", "Finished") and (c["date"] or "") <= today,
                "ended": d.get("status") == "Finished" or ((c["date"] or "9999") < today),
                "badges": c["badges"], "organizer": d.get("organizer"), "description": d.get("description"),
            })
    out.sort(key=lambda e: e["date"] or "")
    missing = sum(1 for e in out if e["lat"] is None)
    by_fmt = {f: sum(1 for e in out if e["format"] == f) for f in ("solo", "team", "2v2")}
    print(f"{len(out)} events {by_fmt}, {missing} without coordinates", file=sys.stderr)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "events": out}, f, ensure_ascii=False, indent=1)
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
