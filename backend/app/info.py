"""Field-guide facts for each yard bird: a Wikipedia summary plus size, weight, lifespan and
conservation status from Wikidata, fetched by the server, cached for 30 days, served from here."""

import asyncio
import json
import logging
import time
from urllib.parse import quote

import httpx

from . import db

log = logging.getLogger("birbtrack.info")
UA = {"User-Agent": "birbTrack/1.0 (+https://github.com/chungus-actual/birbtrack)"}
MAX_AGE = 30 * 86400
VERSION = 2   # bump to refetch everything when the stored shape changes
SCHEMA = """
CREATE TABLE IF NOT EXISTS species_info (
    sci TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
"""
IUCN = {"Q211005": "Least concern", "Q719675": "Near threatened", "Q278113": "Vulnerable",
        "Q11394": "Endangered", "Q219127": "Critically endangered", "Q239509": "Extinct in the wild",
        "Q237350": "Extinct", "Q3245245": "Data deficient"}
UNITS = {"Q174728": ("cm", 1.0), "Q11573": ("cm", 100.0), "Q174789": ("cm", 0.1), "Q218593": ("cm", 2.54),
         "Q41803": ("g", 1.0), "Q11570": ("g", 1000.0), "Q100995": ("g", 453.592), "Q48013": ("g", 28.3495),
         "Q577": ("yr", 1.0), "Q23387": ("yr", 1 / 52.1775), "Q5151": ("yr", 1 / 12)}
PROPS = {"length": "P2043", "wingspan": "P2050", "mass": "P2067", "lifespan": "P2250"}


def init():
    db.conn().executescript(SCHEMA)


def get(sci: str) -> dict | None:
    row = db.conn().execute("SELECT data FROM species_info WHERE sci = ?", (sci,)).fetchone()
    return json.loads(row[0]) if row else None


def _quantity(claims: dict, prop: str):
    vals = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if not isinstance(v, dict) or "amount" not in v:
            continue
        unit = v.get("unit", "").rsplit("/", 1)[-1]
        if unit in UNITS:
            name, factor = UNITS[unit]
            vals.append((name, float(v["amount"]) * factor))
    if not vals:
        return None
    name = vals[0][0]
    nums = sorted(n for u, n in vals if u == name)
    return {"unit": name, "min": round(nums[0], 1), "max": round(nums[-1], 1)}


async def fetch(client: httpx.AsyncClient, sci: str, common: str) -> dict:
    out = {"v": VERSION, "summary": None, "intro": None, "wikipedia": None, "status": None}
    for title in (common, sci):
        r = await client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}",
                             headers=UA, follow_redirects=True)
        if r.status_code == 200 and r.json().get("type") == "standard":
            page = r.json()
            out["summary"] = page.get("extract")
            out["wikipedia"] = page.get("content_urls", {}).get("desktop", {}).get("page")
            qid = page.get("wikibase_item")
            # the whole lead section, not just its first sentences
            r = await client.get("https://en.wikipedia.org/w/api.php", headers=UA, params={
                "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
                "titles": page.get("title", title), "format": "json", "formatversion": 2})
            if r.status_code == 200:
                pages = r.json().get("query", {}).get("pages", [])
                text = (pages[0].get("extract") or "").strip() if pages else ""
                paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
                out["intro"] = "\n".join(paras[:3]) or None
            break
    else:
        qid = None
    if qid:
        r = await client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", headers=UA,
                             follow_redirects=True)
        if r.status_code == 200:
            claims = r.json().get("entities", {}).get(qid, {}).get("claims", {})
            for key, prop in PROPS.items():
                out[key] = _quantity(claims, prop)
            for c in claims.get("P141", []):
                status = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                if status in IUCN:
                    out["status"] = IUCN[status]
                    break
    return out


async def keep_fresh():
    """Fill missing or month-old entries, gently (one species at a time); re-checked hourly."""
    await asyncio.to_thread(init)
    while True:
        try:
            rows = await asyncio.to_thread(lambda: db.conn().execute(
                "SELECT s.sci, s.common, i.data, i.fetched_at FROM species s "
                "LEFT JOIN species_info i ON i.sci = s.sci").fetchall())
            cutoff = int(time.time()) - MAX_AGE
            stale = [(sci, common) for sci, common, data, at in rows
                     if data is None or at < cutoff or json.loads(data).get("v") != VERSION]
            async with httpx.AsyncClient(timeout=20) as client:
                for sci, common in stale:
                    try:
                        data = await fetch(client, sci, common)
                    except httpx.HTTPError as e:
                        log.info("info %s: %s", sci, e)
                        continue

                    def save():
                        c = db.conn()
                        c.execute("INSERT OR REPLACE INTO species_info (sci, data, fetched_at) VALUES (?, ?, ?)",
                                  (sci, json.dumps(data), int(time.time())))
                        c.commit()
                    await asyncio.to_thread(save)
                    await asyncio.sleep(0.5)
            if stale:
                log.info("species info refreshed for %d species", len(stale))
        except Exception as e:
            log.warning("species info: %s", e)
        await asyncio.sleep(3600)
