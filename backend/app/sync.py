"""Keep the mirror in step with BirdNET-Go: backfill, live stream, and a reconcile sweep.

New detections (first time birbTrack sees them, and recent) go to every listener: the
site's live feed and the Discord notifier. Backfilled history never does.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from . import bng, config, db

log = logging.getLogger("birbtrack.sync")
listeners = []          # async callables (row)
state = {"stream": "starting", "last_event": 0, "last_sync": 0, "backfilled": False}
FRESH = 3600            # only detections younger than this count as news


def today():
    return datetime.now(config.TZ).date()


async def emit(rows, new_ids):
    new = set(new_ids)
    now = time.time()
    for r in rows:
        if r["id"] in new and now - r["ts"] < FRESH and r["verified"] != "false_positive":
            for fn in listeners:
                try:
                    await fn(r)
                except Exception:
                    log.exception("listener failed for detection %s", r["id"])


async def backfill():
    """Pull everything from the day before our newest row (all of it on the first run)."""
    newest = await asyncio.to_thread(lambda: db.conn().execute("SELECT MAX(day) FROM detections").fetchone()[0])
    start = (datetime.fromisoformat(newest).date() - timedelta(days=1)).isoformat() if newest else "2000-01-01"
    end, offset, total = today().isoformat(), 0, 0
    while True:
        p = await bng.page(start, end, offset)
        rows = [bng.to_row(d) for d in p.get("data") or []]
        if rows:
            await asyncio.to_thread(db.upsert, rows, int(time.time()))
        offset += len(rows)
        total = int(p.get("total") or 0)
        if not rows or offset >= total:
            break
    state["backfilled"] = True
    state["last_sync"] = time.time()
    log.info("backfill from %s: %d detections", start, offset)


async def reconcile(days: int):
    """Re-read the last `days` days: picks up anything the stream missed, reviews, deletions."""
    for i in range(days):
        day = (today() - timedelta(days=i)).isoformat()
        rows = [bng.to_row(d) for d in await bng.day_all(day)]
        new_ids = await asyncio.to_thread(db.upsert, rows, int(time.time())) if rows else []
        gone = await asyncio.to_thread(db.delete_missing, day, [r["id"] for r in rows])
        if new_ids or gone:
            log.info("reconcile %s: %d new, %d gone", day, len(new_ids), gone)
        await emit(rows, new_ids)
    state["last_sync"] = time.time()


async def live():
    backoff = 5
    while True:
        opened = time.monotonic()
        try:
            async for event, data in bng.stream():
                state["stream"] = "connected"
                state["last_event"] = time.time()
                if event != "detection":
                    continue
                d = bng.parse(data)
                if not d or "scientificName" not in d:
                    continue
                row = bng.to_row(d)
                new_ids = await asyncio.to_thread(db.upsert, [row], int(time.time()))
                await emit([row], new_ids)
            backoff = 5          # the server ends every stream after 30 min: just reopen
        except Exception as e:
            state["stream"] = f"down: {type(e).__name__}"
            log.warning("detection stream: %s: %s", type(e).__name__, e)
        if time.monotonic() - opened < 30:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)
        try:
            await reconcile(1)
        except Exception as e:
            log.warning("catch-up after stream drop failed: %s", e)


async def taxonomy():
    """Fill family/order/rarity for species that lack them (rarity's coordinates are dropped)."""
    missing = await asyncio.to_thread(lambda: [r[0] for r in db.conn().execute(
        "SELECT sci FROM species WHERE family IS NULL")])
    for sci in missing:
        try:
            info = await bng.species_info(sci)
        except Exception as e:
            log.warning("species info %s: %s", sci, e)
            continue
        tax = info.get("taxonomy") or {}
        rarity = (info.get("rarity") or {}).get("status")

        def save():
            c = db.conn()
            c.execute("UPDATE species SET family = ?, family_common = ?, ord = ?, rarity = ? WHERE sci = ?",
                      (tax.get("family") or "", tax.get("family_common") or "", tax.get("order") or "",
                       rarity, sci))
            c.commit()
        await asyncio.to_thread(save)


async def periodic():
    nightly_done = None
    while True:
        await asyncio.sleep(300)
        try:
            await reconcile(2)
            now = datetime.now(config.TZ)
            if now.hour == 3 and nightly_done != now.date():
                await reconcile(30)
                await taxonomy()
                nightly_done = now.date()
        except Exception as e:
            log.warning("periodic sync: %s", e)


async def run():
    """Started once by the web app; retries the first backfill until BirdNET-Go answers."""
    while True:
        try:
            await backfill()
            break
        except Exception as e:
            state["stream"] = f"waiting for BirdNET-Go: {type(e).__name__}"
            log.warning("backfill: %s", e)
            await asyncio.sleep(15)
    asyncio.create_task(taxonomy())
    await asyncio.gather(live(), periodic())
