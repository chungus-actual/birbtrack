"""Where each yard bird is likely, month by month, across the Americas.

BirdNET's own geomodel (the range filter BirdNET-Go uses to decide which species are plausible at a
place and week) sampled on a land-only grid over one region (maps/<region>.json, built by
tools/build_map.py from Natural Earth). One BirdNET-Go call returns every species' score for one point
and week, so a full build is points x 12 months; scores are stored as one byte per point per month.
"""

import asyncio
import json
import logging
import math
import time
from pathlib import Path

from . import bng, config, db

log = logging.getLogger("birbtrack.ranges")
MAPS = Path(__file__).with_name("maps")
GRID: dict | None = None      # the region's map, once the station's location is known (place.py)
POINTS: list = []
VERSION = ""
# BirdNET's year has 48 weeks, 4 per month: the middle of each month
WEEKS = [m * 4 + 2 for m in range(12)]
state = {"building": False, "done": 0, "total": 0}


def pick(lat: float, lon: float) -> str:
    """BT_REGION, or the region whose box holds the station (the nearest box centre when several or none do)."""
    if config.REGION != "auto":
        return config.REGION
    boxes = {p.stem: json.loads(p.read_text(encoding="utf-8"))["box"] for p in MAPS.glob("*.json")}
    inside = [k for k, (x0, x1, y0, y1) in boxes.items() if x0 <= lon <= x1 and y0 <= lat <= y1]
    centre = lambda k: math.dist(((boxes[k][0] + boxes[k][1]) / 2, (boxes[k][2] + boxes[k][3]) / 2), (lon, lat))
    return min(inside or boxes, key=centre)


def load():
    global GRID, POINTS, VERSION
    key = pick(config.LAT, config.LON)
    grid = json.loads((MAPS / f"{key}.json").read_text(encoding="utf-8"))
    POINTS = grid["points"]
    VERSION = f"{key}:{grid['step']}:{len(POINTS)}"
    state["total"] = len(POINTS) * 12
    GRID = grid

SCHEMA = """
CREATE TABLE IF NOT EXISTS ranges (
    sci TEXT NOT NULL,
    month INTEGER NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (sci, month)
);
"""


def project(lat: float, lon: float) -> tuple[float, float]:
    """The same Equal Earth projection and scaling as the basemap."""
    A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
    lam = math.radians(lon - GRID["central"])
    th = math.asin(math.sqrt(3) / 2 * math.sin(math.radians(lat)))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(th) / (3 * (9 * A4 * t6 * t2 + 7 * A3 * t6 + 3 * A2 * t2 + A1))
    y = -(A4 * t6 * t2 * th + A3 * t6 * th + A2 * t2 * th + A1 * th)
    return round((x - GRID["minx"]) * GRID["k"], 1), round((y - GRID["miny"]) * GRID["k"], 1)


def init():
    db.conn().executescript(SCHEMA)


def missing() -> list[str]:
    if GRID is None:
        return []
    c = db.conn()
    stored = db.get_meta("range_version") or ""
    if stored.count(":") == 1:      # from before regions: "step:points", always the Americas
        stored = f"americas:{stored}"
    if stored != VERSION:
        return [r[0] for r in c.execute("SELECT sci FROM species")]
    return [r[0] for r in c.execute(
        "SELECT s.sci FROM species s LEFT JOIN (SELECT sci, COUNT(*) n FROM ranges GROUP BY sci) r "
        "ON r.sci = s.sci WHERE COALESCE(r.n, 0) < 12")]


def months(sci: str) -> list[bytes] | None:
    rows = db.conn().execute("SELECT month, data FROM ranges WHERE sci = ? ORDER BY month", (sci,)).fetchall()
    if len(rows) != 12:
        return None
    return [r[1] for r in rows]


async def build():
    """Sample every grid point for every month; fills all species at once (one call scores them all)."""
    want = await asyncio.to_thread(lambda: [r[0] for r in db.conn().execute("SELECT sci FROM species")])
    if not want or state["building"]:
        return
    state.update(building=True, done=0)
    started = time.monotonic()
    grids = {sci: [bytearray(len(POINTS)) for _ in range(12)] for sci in want}
    sem = asyncio.Semaphore(6)

    async def sample(i: int, month: int):
        lat, lon = POINTS[i][0], POINTS[i][1]
        async with sem:
            for attempt in range(3):
                try:
                    r = await bng.client().get("/range/species/scores", params={
                        "lat": lat, "lon": lon, "week": WEEKS[month], "names": "false"})
                    r.raise_for_status()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2)
        scores = await asyncio.to_thread(lambda: {s["scientificName"]: s["score"] for s in r.json()["species"]})
        for sci, g in grids.items():
            g[month][i] = min(255, round(scores.get(sci, 0.0) * 255))
        state["done"] += 1

    try:
        for month in range(12):
            await asyncio.gather(*(sample(i, month) for i in range(len(POINTS))))

        def save():
            c = db.conn()
            c.executemany("INSERT OR REPLACE INTO ranges (sci, month, data) VALUES (?, ?, ?)",
                          [(sci, m, bytes(g[m])) for sci, g in grids.items() for m in range(12)])
            c.commit()
            db.set_meta("range_version", VERSION)
        await asyncio.to_thread(save)
        log.info("ranges: %d species x 12 months from %d points in %.0f s", len(grids), len(POINTS),
                 time.monotonic() - started)
    finally:
        state["building"] = False


async def keep_fresh():
    """Build on first start, and again whenever a species without a range shows up (checked hourly)."""
    await asyncio.to_thread(init)
    while GRID is None:
        await asyncio.sleep(5)
    while True:
        try:
            if await asyncio.to_thread(missing):
                await build()
        except Exception as e:
            log.warning("range build: %s", e)
        await asyncio.sleep(3600)
