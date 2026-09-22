#!/usr/bin/env python3
"""Merge data/bcp.json and data/mhq.json into site/events.js and data/events.json.

Adds the French département and région (from the postal code), flags events that
appear on both sites (same day, within 10 km, similar name) and embeds the result
as `window.EVENTS_DATA` so the site works when opened straight from the disk.
"""
import datetime as dt, json, math, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = {
    "Auvergne-Rhône-Alpes": "01 03 07 15 26 38 42 43 63 69 73 74",
    "Bourgogne-Franche-Comté": "21 25 39 58 70 71 89 90",
    "Bretagne": "22 29 35 56",
    "Centre-Val de Loire": "18 28 36 37 41 45",
    "Corse": "2A 2B 20",
    "Grand Est": "08 10 51 52 54 55 57 67 68 88",
    "Hauts-de-France": "02 59 60 62 80",
    "Île-de-France": "75 77 78 91 92 93 94 95",
    "Normandie": "14 27 50 61 76",
    "Nouvelle-Aquitaine": "16 17 19 23 24 33 40 47 64 79 86 87",
    "Occitanie": "09 11 12 30 31 32 34 46 48 65 66 81 82",
    "Pays de la Loire": "44 49 53 72 85",
    "Provence-Alpes-Côte d'Azur": "04 05 06 13 83 84",
    "Outre-mer": "971 972 973 974 976 986 987 988",
}
DEPT_TO_REGION = {d: r for r, ds in REGIONS.items() for d in ds.split()}


def dept_from_zip(z):
    if not z:
        return None
    z = re.sub(r"\D", "", str(z))
    if len(z) != 5:
        return None
    if z.startswith("97") or z.startswith("98"):
        return z[:3]
    if z.startswith("20"):
        return "2A" if int(z) < 20200 else "2B"
    return z[:2]


def haversine(a, b):
    if None in (a["lat"], a["lon"], b["lat"], b["lon"]):
        return 1e9
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def tokens(name):
    return {t for t in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if t not in {"tournoi", "tournament", "warhammer", "40k", "40000", "000", "2000", "pts", "points", "the", "les", "des"}}


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.34


def load(name):
    p = os.path.join(HERE, "data", name)
    if not os.path.exists(p):
        print(f"missing {p}, skipping")
        return {"events": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    bcp, mhq = load("bcp.json"), load("mhq.json")
    events = bcp["events"] + mhq["events"]
    for e in events:
        z = e.get("zip") or (re.search(r"\b(\d{5})\b", e.get("address") or "") or [None, None])[1]
        e["zip"] = z
        e["dept"] = dept_from_zip(z)
        e["region"] = DEPT_TO_REGION.get(e["dept"] or "", e.get("region")) if e["dept"] else (e.get("region") or None)
        if e["source"] == "bcp" and e.get("region") and e["region"] not in REGIONS:
            e["region"] = None
        e["urls"] = {e["source"]: e["url"]}

    merged = 0
    by_date = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e)
    drop = set()
    for date, group in by_date.items():
        bs = [e for e in group if e["source"] == "bcp"]
        ms = [e for e in group if e["source"] == "mhq"]
        for b in bs:
            for m in ms:
                if m["id"] in drop:
                    continue
                if haversine(b, m) <= 10 and similar(b["name"], m["name"]):
                    b["urls"]["mhq"] = m["url"]
                    b["source"] = "both"
                    b["altName"] = m["name"]
                    for k in ("rounds", "organizer", "city", "zip", "dept", "region", "description"):
                        if not b.get(k) and m.get(k):
                            b[k] = m[k]
                    b["mhq"] = {"players": m.get("players"), "capacity": m.get("capacity"), "interested": m.get("interested"), "status": m.get("status")}
                    drop.add(m["id"])
                    merged += 1
                    break
    events = [e for e in events if e["id"] not in drop]
    events.sort(key=lambda e: (e["date"] or "", e["name"] or ""))

    today = dt.date.today().isoformat()
    stats = {
        "total": len(events), "upcoming": sum(1 for e in events if (e["date"] or "") >= today),
        "past": sum(1 for e in events if (e["date"] or "") < today),
        "noCoords": sum(1 for e in events if e.get("lat") is None), "merged": merged,
        "bcp": sum(1 for e in events if "bcp" in e["urls"]), "mhq": sum(1 for e in events if "mhq" in e["urls"]),
    }
    payload = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": {"bcp": bcp.get("fetchedAt"), "mhq": mhq.get("fetchedAt")},
        "regions": list(REGIONS.keys()), "stats": stats, "events": events,
    }
    os.makedirs(os.path.join(HERE, "site"), exist_ok=True)
    with open(os.path.join(HERE, "data", "events.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "site", "events.js"), "w", encoding="utf-8") as f:
        f.write("window.EVENTS_DATA = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
