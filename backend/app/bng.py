"""BirdNET-Go's v2 API, as birbTrack uses it (tested with release 20261014, no login)."""

import json
from datetime import datetime

import httpx

from . import config

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=f"{config.BNG_URL}/api/v2",
                                    timeout=httpx.Timeout(20.0, read=60.0),
                                    limits=httpx.Limits(max_connections=20))
    return _client


def to_row(d: dict) -> dict:
    """A BirdNET-Go detection (list item or SSE payload) as a birbTrack row."""
    ts = _ts(d)
    local = datetime.fromtimestamp(ts, config.TZ)
    return {
        "id": int(d["id"]),
        "ts": ts,
        "day": local.strftime("%Y-%m-%d"),
        "hms": local.strftime("%H:%M:%S"),
        "sci": d["scientificName"],
        "common": d.get("commonName") or d["scientificName"],
        "code": d.get("speciesCode") or None,
        "confidence": round(float(d.get("confidence") or 0), 4),
        "clip": 1 if d.get("clipName") else 0,
        "verified": d.get("verified") or "unverified",
    }


def _ts(d: dict) -> int:
    # list items carry an ISO timestamp with the offset; the SSE payload's may be the event
    # time instead, so anything but an ISO string falls back to the detection's wall clock
    t = d.get("timestamp")
    if isinstance(t, str) and "T" in t:
        try:
            return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    local = datetime.strptime(f"{d['date']} {d['time'][:8]}", "%Y-%m-%d %H:%M:%S")
    return int(local.replace(tzinfo=config.TZ).timestamp())


async def page(start: str, end: str, offset: int = 0, limit: int = 1000) -> dict:
    r = await client().get("/detections", params={
        "start_date": start, "end_date": end, "sortBy": "date_asc", "limit": limit, "offset": offset})
    r.raise_for_status()
    return r.json()


async def day_all(day: str) -> list[dict]:
    out, offset = [], 0
    while True:
        p = await page(day, day, offset)
        data = p.get("data") or []
        out.extend(data)
        offset += len(data)
        if not data or offset >= int(p.get("total") or 0):
            return out


async def species_info(sci: str) -> dict:
    r = await client().get("/species", params={"scientific_name": sci})
    r.raise_for_status()
    return r.json()


async def stream():
    """Yield (event, data) from the live detection stream until the server closes it."""
    async with client().stream("GET", "/detections/stream",
                               timeout=httpx.Timeout(10.0, read=60.0)) as r:
        r.raise_for_status()
        event, data = "message", []
        async for line in r.aiter_lines():
            if line == "":
                if data:
                    yield event, "\n".join(data)
                event, data = "message", []
            elif line.startswith(":"):
                continue
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())


def parse(data: str):
    try:
        return json.loads(data)
    except ValueError:
        return None
