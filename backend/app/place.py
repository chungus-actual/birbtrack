"""Where the station is: BT_LAT/BT_LON when set, otherwise BirdNET-Go's own location setting, read at
startup. Only sunrise and sunset, the map region and the yard dot on it use it; coordinates are never
served."""

import asyncio
import logging

from . import bng, config, ranges, stats

log = logging.getLogger("birbtrack.place")


async def resolve():
    while config.LAT is None or config.LON is None:
        try:
            r = await bng.client().get("/settings/birdnet")
            r.raise_for_status()
            s = r.json()
            if s.get("locationConfigured", True) and (s.get("latitude") or s.get("longitude")):
                config.LAT, config.LON = float(s["latitude"]), float(s["longitude"])
                log.info("station location read from BirdNET-Go")
                break
            log.warning("BirdNET-Go has no location yet: set it there, or BT_LAT and BT_LON")
        except Exception as e:
            log.info("station location: %s", e)
        await asyncio.sleep(30)
    await asyncio.to_thread(ranges.load)
    stats.invalidate()
    log.info("range map: %s", ranges.GRID["name"])
