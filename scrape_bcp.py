#!/usr/bin/env python3
"""Fetch Warhammer 40k events located in France from the Best Coast Pairings API.

BCP exposes an undocumented JSON API used by its React front-end:
  GET https://newprod-api.bestcoastpairings.com/v1/events   (header: client-id: web-app)
Geographic filtering is done with a `location` JSON parameter (distance in miles),
pagination with `nextKey`. We query a radius around metropolitan France plus the
overseas territories, then keep only events whose country/address is France.
"""
import argparse, json, os, re, sys, time, datetime as dt, urllib.parse, urllib.request

API = "https://newprod-api.bestcoastpairings.com/v1/events"
GAME_40K = "WGMSzfKFYA"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
KM_TO_MILES = 0.6214

# (label, lat, lon, radius_km)
REGIONS = [
    ("metropole", 46.227638, 2.213749, 820),
    ("antilles", 15.5, -61.5, 450),
    ("guyane", 4.5, -53.0, 450),
    ("reunion-mayotte", -19.0, 50.0, 1300),
    ("nouvelle-caledonie", -21.5, 165.5, 500),
    ("polynesie", -17.6, -149.5, 600),
]
FR_COUNTRIES = {"france", "fr", "france métropolitaine", "france metropolitaine", "french republic",
                "république française", "republique francaise", "guadeloupe", "martinique", "réunion",
                "reunion", "la réunion", "la reunion", "guyane", "guyane française", "french guiana",
                "mayotte", "nouvelle-calédonie", "nouvelle caledonie", "new caledonia",
                "polynésie française", "french polynesia", "saint-martin", "saint-barthélemy", "corse"}
FR_ADDRESS_TAILS = ("france", "guadeloupe", "martinique", "réunion", "reunion", "guyane française",
                    "french guiana", "mayotte", "nouvelle-calédonie", "new caledonia",
                    "polynésie française", "french polynesia")


def is_france(ev):
    c = (ev.get("country") or "").strip().lower()
    if c in FR_COUNTRIES:
        return True
    addr = (ev.get("formatted_address") or "").strip().lower().rstrip(".")
    return any(addr.endswith(t) for t in FR_ADDRESS_TAILS)


def get(params, retries=4):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"client-id": "web-app", "Accept": "application/json", "User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  ! {e} (retry in {wait}s)", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit("BCP API unreachable")


def fetch_region(label, lat, lon, radius_km, start, end, game):
    loc = json.dumps({"distance": round(radius_km * KM_TO_MILES, 2), "center": {"lat": lat, "long": lon}, "distanceType": "kms"})
    base = {"limit": 100, "startDate": f"{start}T00:00:00Z", "endDate": f"{end}T23:59:59Z", "gameSystemId": game,
            "excludeOnline": "true", "sortKey": "eventDate", "sortAscending": "true", "distanceType": "kms", "location": loc}
    seen_keys, out, next_key, page = set(), [], None, 0
    while True:
        params = dict(base)
        if next_key:
            params["nextKey"] = next_key
        res = get(params)
        data = res.get("data") or []
        out.extend(data)
        page += 1
        print(f"  [{label}] page {page}: {len(data)} events (total {len(out)})", file=sys.stderr)
        next_key = res.get("nextKey")
        if not data or not next_key or next_key in seen_keys:
            break
        seen_keys.add(next_key)
        time.sleep(0.3)
    return out


def fetch_detail(event_id):
    """The list API only says teamEvent; the per-event record adds doublesEvent (2v2)."""
    url = f"{API}/{event_id}"
    req = urllib.request.Request(url, headers={"client-id": "web-app", "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"  ! detail {event_id}: {e}", file=sys.stderr)
        return {}


def normalize(ev):
    coord = ev.get("coordinate") or [None, None]
    team = bool(ev.get("teamEvent"))
    doubles = bool(ev.get("doublesEvent"))
    name_says_2v2 = bool(re.search(r"\b2\s*v\s*2\b|double|duo|bin[oô]me", ev.get("name") or "", re.I))
    fmt = "2v2" if team and (doubles or name_says_2v2) else "team" if team else "solo"
    size_in_name = re.search(r"\b(\d)\s*v\s*\1\b", ev.get("name") or "")
    return {
        "source": "bcp",
        "id": f"bcp:{ev['id']}",
        "name": ev.get("name"),
        "url": f"https://www.bestcoastpairings.com/event/{ev['id']}",
        "game": ev.get("gameSystemName") or "Warhammer 40,000",
        "date": (ev.get("eventDate") or "")[:10],
        "endDate": (ev.get("eventEndDate") or "")[:10],
        "format": fmt,
        "teamSize": 2 if fmt == "2v2" else (int(size_in_name.group(1)) if size_in_name else None),
        "venue": ev.get("locationName"),
        "address": ev.get("formatted_address"),
        "city": ev.get("city"),
        "region": ev.get("state"),
        "zip": ev.get("zip"),
        "country": ev.get("country"),
        "lat": coord[1], "lon": coord[0],
        "players": ev.get("totalPlayers"),
        "capacity": ev.get("numTickets"),
        "rounds": ev.get("numberOfRounds"),
        "teamEvent": bool(ev.get("teamEvent")),
        "started": bool(ev.get("started")),
        "ended": bool(ev.get("ended")),
        "price": ev.get("ticketPrice"),
        "currency": next(iter((ev.get("pricingDict") or {}).keys()), None),
        "leagues": [l.get("name") for l in (ev.get("leagues") or []) if isinstance(l, dict)],
        "organizer": " ".join(x for x in [ev.get("ownerFirstName"), ev.get("ownerLastName")] if x) or None,
        "photo": ev.get("photoUrl"),
        "description": (ev.get("description") or "")[:600],
        "updatedAt": ev.get("updated_at"),
    }


def main():
    today = dt.date.today()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=(today - dt.timedelta(days=365)).isoformat())
    ap.add_argument("--end", default=(today + dt.timedelta(days=548)).isoformat())
    ap.add_argument("--game", default=GAME_40K, help="BCP gameSystemId (default: Warhammer 40k)")
    ap.add_argument("--out", default="data/bcp.json")
    a = ap.parse_args()

    raw, by_id = [], {}
    for label, lat, lon, radius in REGIONS:
        for ev in fetch_region(label, lat, lon, radius, a.start, a.end, a.game):
            if ev["id"] not in by_id:
                by_id[ev["id"]] = ev
                raw.append(ev)
    fr_raw = [e for e in raw if is_france(e)]
    for e in fr_raw:
        if e.get("teamEvent"):
            e["doublesEvent"] = bool(fetch_detail(e["id"]).get("doublesEvent"))
            time.sleep(0.2)
    fr = [normalize(e) for e in fr_raw]
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            previous = json.load(f).get("events", [])
        ids = {e["id"] for e in fr}
        kept = [e for e in previous if e["id"] not in ids and not (a.start <= e["date"] <= a.end)]
        if kept:
            print(f"kept {len(kept)} previously fetched events outside {a.start}..{a.end}", file=sys.stderr)
        fr.extend(kept)
    fr.sort(key=lambda e: e["date"])
    countries = {}
    for e in raw:
        countries[e.get("country")] = countries.get(e.get("country"), 0) + 1
    print(f"fetched {len(raw)} events in radius, kept {len(fr)} in France", file=sys.stderr)
    print("top countries seen:", sorted(countries.items(), key=lambda kv: -kv[1])[:12], file=sys.stderr)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "start": a.start, "end": a.end, "events": fr}, f, ensure_ascii=False, indent=1)
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
