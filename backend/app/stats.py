"""Read models for the site and the weekly report.

Everything is computed from the mirror. Results are cached for a few seconds and the cache
is cleared whenever a new detection lands.
"""

import json
import random
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, db, images, info
from .db import VISIBLE
from .sun import sun_times

def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


# keyed by BirdNET-Pi's names ("Black-crowned Night-Heron"); BirdNET-Go says "Night Heron"
_FACTS = {_norm(k): v for k, v in json.loads(
    Path(__file__).with_name("facts.json").read_text(encoding="utf-8")).items()}


class _Facts:
    def get(self, common, default=None):
        return _FACTS.get(_norm(common or ""), default)

    def __getitem__(self, common):
        return _FACTS[_norm(common)]


FACTS = _Facts()

_cache: dict = {}
_lock = threading.Lock()


def cached(ttl):
    def deco(fn):
        def wrap(*args):
            key = (fn.__name__, *args)
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            value = fn(*args)
            with _lock:
                _cache[key] = (time.monotonic(), value)
            return value
        return wrap
    return deco


def invalidate():
    with _lock:
        _cache.clear()


def today() -> date:
    return datetime.now(config.TZ).date()


def secs(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s


def fmt_time(hms: str) -> str:
    h, m = int(hms[:2]), int(hms[3:5])
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


@cached(60)
def species_index() -> dict:
    return {r["sci"]: dict(r) for r in db.conn().execute("SELECT * FROM species")}


@cached(60)
def first_seen() -> dict:
    """sci -> (first day, first detection id) over the whole history: the yard list."""
    out = {}
    for r in db.conn().execute(f"""
            SELECT sci, day, id FROM (
              SELECT sci, day, id, ROW_NUMBER() OVER (PARTITION BY sci ORDER BY ts, id) AS rn
              FROM detections WHERE {VISIBLE}) WHERE rn = 1 ORDER BY day, id"""):
        out[r["sci"]] = (r["day"], r["id"])
    return out


def yard_number(sci: str) -> int | None:
    order = list(first_seen())
    return order.index(sci) + 1 if sci in order else None


def card(sci: str) -> dict:
    """The few fields every page shows for a species."""
    s = species_index().get(sci) or {"common": sci, "slug": db.slugify(sci)}
    return {"sci": sci, "common": s["common"], "slug": s["slug"],
            "family": s.get("family_common") or None, "photo": images.has_photo(sci)}


def detection_brief(r) -> dict:
    return {"id": r["id"], "day": r["day"], "time": r["hms"], "confidence": round(r["confidence"], 3),
            "clip": bool(r["clip"]), **card(r["sci"])}


def sun(d: date) -> dict:
    if config.LAT is None:
        return {"sunrise": "06:00:00", "sunset": "18:00:00"}   # until the location is known
    rise, set_ = sun_times(d, config.LAT, config.LON, config.TZ)
    return {"sunrise": rise.strftime("%H:%M:%S") if rise else None,
            "sunset": set_.strftime("%H:%M:%S") if set_ else None}


@cached(10)
def day(d: str) -> dict:
    c = db.conn()
    rows = c.execute(f"SELECT id, ts, day, hms, sci, confidence, clip FROM detections "
                     f"WHERE day = ? AND {VISIBLE} ORDER BY ts, id", (d,)).fetchall()
    firsts = first_seen()
    present = sorted({r["sci"] for r in rows})
    before = {}
    if present:
        before = {r[0]: r[1] for r in c.execute(
            f"SELECT sci, MAX(day) FROM detections WHERE day < ? AND {VISIBLE} "
            f"AND sci IN ({','.join('?' * len(present))}) GROUP BY sci", (d, *present))}
    per = {}
    for r in rows:
        s = per.get(r["sci"])
        if s is None:
            s = per[r["sci"]] = {**card(r["sci"]), "count": 0, "first": r["hms"], "last": r["hms"],
                                 "hourly": [0] * 24, "max_confidence": 0.0, "best": None, "_best": -1.0}
        s["count"] += 1
        s["last"] = r["hms"]
        s["hourly"][int(r["hms"][:2])] += 1
        s["max_confidence"] = max(s["max_confidence"], round(r["confidence"], 3))
        if r["clip"] and r["confidence"] > s["_best"]:
            s["_best"], s["best"] = r["confidence"], r["id"]
    species = []
    dd = date.fromisoformat(d)
    for sci, s in per.items():
        s.pop("_best")
        s["lifer"] = firsts.get(sci, (None,))[0] == d
        prev = before.get(sci)
        gap = (dd - date.fromisoformat(prev)).days if prev else None
        s["back_after"] = gap if gap and gap >= config.COMEBACK_DAYS else None
        species.append(s)
    species.sort(key=lambda s: s["first"])
    index = {s["sci"]: i for i, s in enumerate(species)}
    nav = c.execute(f"SELECT (SELECT MAX(day) FROM detections WHERE day < ? AND {VISIBLE}), "
                    f"(SELECT MIN(day) FROM detections WHERE day > ? AND {VISIBLE})", (d, d)).fetchone()
    latest = detection_brief(rows[-1]) if rows else None
    return {
        "date": d, "is_today": d == today().isoformat(), "tz": config.TZ.key, **sun(dd),
        "total": len(rows), "species_count": len(species),
        "points": [[secs(r["hms"]), index[r["sci"]], r["id"]] for r in rows],
        "species": species, "latest": latest, "prev": nav[0], "next": nav[1],
    }


@cached(30)
def species_list() -> dict:
    since = int(time.time()) - 30 * 86400
    firsts = first_seen()
    out = []
    for r in db.conn().execute(f"""
            SELECT sci, COUNT(*) AS n, COUNT(DISTINCT day) AS days, MIN(day) AS first, MAX(day) AS last,
                   MAX(ts) AS last_ts, SUM(ts > ?) AS recent
            FROM detections WHERE {VISIBLE} GROUP BY sci""", (since,)):
        out.append({**card(r["sci"]), "count": r["n"], "days": r["days"], "first": r["first"],
                    "last": r["last"], "recent": r["recent"],
                    "yard_number": list(firsts).index(r["sci"]) + 1 if r["sci"] in firsts else None})
    out.sort(key=lambda s: -s["count"])
    return {"species": out, "total": len(out)}


@cached(30)
def species_detail(slug: str) -> dict | None:
    c = db.conn()
    s = c.execute("SELECT * FROM species WHERE slug = ?", (slug,)).fetchone()
    if not s:
        return None
    sci = s["sci"]
    agg = c.execute(f"SELECT COUNT(*) AS n, COUNT(DISTINCT day) AS days, MIN(day) AS first, MAX(day) AS last, "
                    f"MAX(confidence) AS best FROM detections WHERE sci = ? AND {VISIBLE}", (sci,)).fetchone()
    if not agg["n"]:
        return None
    hourly = [0] * 24
    year = {}          # "week:hour" -> count, weeks of the year 0..52
    calendar = {}
    for r in c.execute(f"SELECT day, hms FROM detections WHERE sci = ? AND {VISIBLE}", (sci,)):
        h = int(r["hms"][:2])
        hourly[h] += 1
        wk = min(52, (date.fromisoformat(r["day"]).timetuple().tm_yday - 1) // 7)
        year[f"{wk}:{h}"] = year.get(f"{wk}:{h}", 0) + 1
        calendar[r["day"]] = calendar.get(r["day"], 0) + 1
    recent = [detection_brief(r) for r in c.execute(
        f"SELECT * FROM detections WHERE sci = ? AND {VISIBLE} ORDER BY ts DESC LIMIT 12", (sci,))]
    best = [detection_brief(r) for r in c.execute(
        f"SELECT * FROM detections WHERE sci = ? AND clip = 1 AND {VISIBLE} "
        f"ORDER BY confidence DESC, ts DESC LIMIT 3", (sci,))]
    first_id = first_seen().get(sci, (None, None))[1]
    about = info.get(sci) or {}
    links = {"allaboutbirds": "https://www.allaboutbirds.org/guide/" + s["common"].replace("'", "").replace(" ", "_")}
    if s["code"]:
        links["ebird"] = f"https://ebird.org/species/{s['code']}"
    if about.get("wikipedia"):
        links["wikipedia"] = about["wikipedia"]
    heard_months = sorted({int(d[5:7]) - 1 for d in calendar})
    return {
        **card(sci), "order": s["ord"] or None, "rarity": s["rarity"],
        "fact": FACTS.get(s["common"]), "credit": images.credit(sci),
        "count": agg["n"], "days": agg["days"], "first": agg["first"], "last": agg["last"],
        "max_confidence": round(agg["best"], 3), "yard_number": yard_number(sci), "first_id": first_id,
        "hourly": hourly, "year": year, "calendar": calendar, "recent": recent, "best": best,
        "about": {k: about.get(k) for k in ("summary", "intro", "status", "length", "wingspan", "mass", "lifespan")},
        "links": links, "heard_months": heard_months, "tz": config.TZ.key,
    }


def week_bounds(key: str) -> tuple[date, date]:
    y, w = key.split("-W")
    monday = date.fromisocalendar(int(y), int(w), 1)
    return monday, monday + timedelta(days=6)


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _change(cur, prev):
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100)


@cached(30)
def week(key: str) -> dict:
    c = db.conn()
    start, end = week_bounds(key)
    s, e = start.isoformat(), end.isoformat()
    ps, pe = (start - timedelta(days=7)).isoformat(), (start - timedelta(days=1)).isoformat()
    rows = c.execute(f"SELECT id, day, hms, sci, confidence, clip FROM detections "
                     f"WHERE day BETWEEN ? AND ? AND {VISIBLE} ORDER BY ts", (s, e)).fetchall()
    prev_total, prev_species = c.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT sci) FROM detections WHERE day BETWEEN ? AND ? AND {VISIBLE}",
        (ps, pe)).fetchone()
    prev_set = {r[0] for r in c.execute(
        f"SELECT DISTINCT sci FROM detections WHERE day BETWEEN ? AND ? AND {VISIBLE}", (ps, pe))}
    firsts = first_seen()

    per, daily, hourly, day_species = {}, {}, [0] * 24, {}
    for i in range(7):
        daily[(start + timedelta(days=i)).isoformat()] = 0
    for r in rows:
        p = per.setdefault(r["sci"], {"count": 0, "max": 0.0, "sum": 0.0, "days": set()})
        p["count"] += 1
        p["max"] = max(p["max"], r["confidence"])
        p["sum"] += r["confidence"]
        p["days"].add(r["day"])
        daily[r["day"]] += 1
        hourly[int(r["hms"][:2])] += 1
        day_species.setdefault(r["day"], set()).add(r["sci"])
    species = sorted(({**card(sci), "count": p["count"], "max_confidence": round(p["max"], 3),
                       "avg_confidence": round(p["sum"] / p["count"], 3), "days": len(p["days"])}
                      for sci, p in per.items()), key=lambda x: (-x["count"], -x["max_confidence"]))

    returning = []
    if per:
        names = list(per)
        for sci, last in c.execute(
                f"SELECT sci, MAX(day) FROM detections WHERE day < ? AND {VISIBLE} "
                f"AND sci IN ({','.join('?' * len(names))}) GROUP BY sci", (s, *names)):
            gap = (start - date.fromisoformat(last)).days
            if gap >= config.COMEBACK_DAYS:
                returning.append({**card(sci), "days_away": gap})
    returning.sort(key=lambda x: -x["days_away"])

    # 00:00-03:59 calls from day birds are mostly noise, so neither award looks there
    early = min((r for r in rows if r["hms"] >= "04:00:00"), key=lambda r: r["hms"], default=None)
    late = max((r for r in rows if r["hms"] >= "12:00:00"), key=lambda r: r["hms"], default=None)
    loyal = max(species, key=lambda x: (x["days"], x["count"]), default=None)
    busiest = max(daily, key=daily.get) if rows else None
    quietest = min(daily, key=daily.get) if rows else None
    life = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT sci) FROM detections WHERE day <= ? AND {VISIBLE}",
                     (e,)).fetchone()
    with_facts = [x for x in species if FACTS.get(x["common"])]
    spot = random.Random(key).choice(with_facts) if with_facts else None
    def has(k):
        a, b = week_bounds(k)
        return c.execute(f"SELECT 1 FROM detections WHERE day BETWEEN ? AND ? AND {VISIBLE} LIMIT 1",
                         (a.isoformat(), b.isoformat())).fetchone() is not None

    prev_key, next_key = week_key(start - timedelta(days=7)), week_key(start + timedelta(days=7))
    return {
        "week": key, "start": s, "end": e, "number": start.isocalendar()[1],
        "total": len(rows), "prev_total": prev_total, "total_change": _change(len(rows), prev_total),
        "species_count": len(species), "prev_species": prev_species,
        "species_change": _change(len(species), prev_species),
        "species": species,
        "lifers": [card(sci) for sci in per if firsts.get(sci, ("",))[0] >= s and firsts[sci][0] <= e],
        "new_vs_last_week": [card(sci) for sci in per if sci not in prev_set],
        "returning": returning[:8],
        "hourly": hourly, "peak_hour": hourly.index(max(hourly)) if rows else None,
        "daily": [{"day": d, "count": n, "species": len(day_species.get(d, ()))} for d, n in daily.items()],
        "early_bird": {**card(early["sci"]), "day": early["day"], "time": early["hms"]} if early else None,
        "night_owl": {**card(late["sci"]), "day": late["day"], "time": late["hms"]} if late else None,
        "most_loyal": {k: loyal[k] for k in ("sci", "common", "slug", "days", "count")} if loyal else None,
        "busiest": {"day": busiest, "count": daily[busiest]} if busiest else None,
        "quietest": {"day": quietest, "count": daily[quietest]} if quietest else None,
        "lifetime": {"detections": life[0], "species": life[1]},
        "spotlight": {**card(spot["sci"]), "fact": FACTS[spot["common"]]} if spot else None,
        "prev": prev_key if has(prev_key) else None, "next": next_key if has(next_key) else None,
    }


@cached(10)
def detection(det_id: int) -> dict | None:
    c = db.conn()
    r = c.execute(f"SELECT * FROM detections WHERE id = ? AND {VISIBLE}", (det_id,)).fetchone()
    if not r:
        return None
    near = [detection_brief(x) for x in c.execute(
        f"SELECT * FROM detections WHERE ts BETWEEN ? AND ? AND id != ? AND {VISIBLE} ORDER BY ts LIMIT 12",
        (r["ts"] - 300, r["ts"] + 300, det_id))]
    same_day = c.execute(f"SELECT COUNT(*) FROM detections WHERE sci = ? AND day = ? AND {VISIBLE}",
                         (r["sci"], r["day"])).fetchone()[0]
    nav = c.execute(f"""SELECT
            (SELECT id FROM detections WHERE sci = ? AND {VISIBLE} AND (ts < ? OR (ts = ? AND id < ?))
             ORDER BY ts DESC, id DESC LIMIT 1),
            (SELECT id FROM detections WHERE sci = ? AND {VISIBLE} AND (ts > ? OR (ts = ? AND id > ?))
             ORDER BY ts, id LIMIT 1)""",
                    (r["sci"], r["ts"], r["ts"], det_id, r["sci"], r["ts"], r["ts"], det_id)).fetchone()
    s = species_index().get(r["sci"], {})
    return {**detection_brief(r), "lifer": first_seen().get(r["sci"], (None, None))[1] == det_id,
            "fact": FACTS.get(s.get("common", "")), "credit": images.credit(r["sci"]),
            "that_day": same_day, "nearby": near, "prev": nav[0], "next": nav[1]}


@cached(10)
def recent(limit: int) -> list:
    return [detection_brief(r) for r in db.conn().execute(
        f"SELECT * FROM detections WHERE {VISIBLE} ORDER BY ts DESC, id DESC LIMIT ?", (limit,))]


@cached(10)
def overview() -> dict:
    c = db.conn()
    t = today().isoformat()
    life = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT sci), MIN(day), COUNT(DISTINCT day) "
                     f"FROM detections WHERE {VISIBLE}").fetchone()
    d = day(t)
    last = c.execute(f"SELECT * FROM detections WHERE {VISIBLE} ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    return {
        "today": t, "lifetime": {"detections": life[0], "species": life[1], "since": life[2], "days": life[3]},
        "today_total": d["total"], "today_species": d["species_count"],
        "today_top": sorted(({k: s[k] for k in ("common", "slug", "count", "first", "last")} for s in d["species"]),
                            key=lambda s: -s["count"])[:8],
        "today_lifers": [s["common"] for s in d["species"] if s["lifer"]],
        "today_back": [{"common": s["common"], "days": s["back_after"]} for s in d["species"] if s["back_after"]],
        "latest": detection_brief(last) if last else None,
        "latest_age_s": int(time.time()) - last["ts"] if last else None,
        **sun(today()),
    }
