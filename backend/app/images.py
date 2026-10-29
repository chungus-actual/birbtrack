"""Species photos: Avicommons (the set BirdNET-Go shows too), cached on disk at 320 and 900 px.

Photos are fetched server-side and served from birbTrack's own origin, so the page never
loads anything from a third party. Avicommons' index (avicommons.org/latest.json) is fetched on
first start and monthly after, kept in the data folder as sci -> [code, key, license, author].
"""

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from . import bng, config, stats

log = logging.getLogger("birbtrack.images")
INDEX_URL = "https://avicommons.org/latest.json"
INDEX_MAX_AGE = 30 * 86400
AVI: dict = {}
# eBird/Clements renames the Avicommons set already uses
SYNONYMS = {"Accipiter cooperii": "Astur cooperii", "Accipiter gentilis": "Astur atricapillus"}
SIZES = (320, 900)
MAX_BYTES = 3 * 1024 * 1024
_locks: dict = {}
_misses: dict = {}


def _read() -> dict:
    p = config.DATA / "avicommons.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


async def _download() -> bool:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(INDEX_URL)
            r.raise_for_status()
            index = {e["sciName"]: [e["code"], e["key"], e["license"], e["by"]] for e in r.json()
                     if e.get("sciName") and e.get("code") and e.get("key")}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("Avicommons index: %s", e)
        return False
    p = config.DATA / "avicommons.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    log.info("Avicommons index: %d species", len(index))
    return True


async def load():
    """At startup: the kept index, or a fresh one on first start (no photos until it arrives)."""
    global AVI
    AVI = await asyncio.to_thread(_read)
    if not AVI and await _download():
        AVI = await asyncio.to_thread(_read)


async def keep_fresh():
    global AVI
    while True:
        p = config.DATA / "avicommons.json"
        age = time.time() - p.stat().st_mtime if p.exists() else INDEX_MAX_AGE
        if age >= INDEX_MAX_AGE and await _download():
            AVI = await asyncio.to_thread(_read)
            _misses.clear()
            stats.invalidate()
        await asyncio.sleep(6 * 3600)


def entry(sci):
    return AVI.get(sci) or AVI.get(SYNONYMS.get(sci, ""))


def has_photo(sci) -> bool:
    return entry(sci) is not None


def license_name(code: str) -> str:
    if code.startswith("CC"):
        return code
    return {"cc0": "CC0", "cc-by": "CC BY", "cc-by-sa": "CC BY-SA", "cc-by-nc": "CC BY-NC",
            "cc-by-nc-sa": "CC BY-NC-SA", "cc-by-nd": "CC BY-ND", "cc-by-nc-nd": "CC BY-NC-ND"}.get(code, code)


def credit(sci):
    e = entry(sci)
    return {"by": e[3], "license": license_name(e[2]), "source": "Avicommons"} if e else None


async def photo(slug: str, sci: str, size: int) -> Path | None:
    """Path to a cached photo, fetching it once; None when there is none to be had."""
    path = config.IMAGES / f"{slug}-{size}.jpg"
    if path.exists():
        return path
    key = (slug, size)
    if time.time() - _misses.get(key, 0) < 3600:
        return None
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if path.exists():
            return path
        data = await _fetch(sci, size)
        if not data:
            _misses[key] = time.time()
            return None
        config.IMAGES.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path


async def _fetch(sci: str, size: int) -> bytes | None:
    e = entry(sci)
    urls = []
    if e:
        urls.append(f"https://static.avicommons.org/{e[0]}-{e[1]}-{size}.jpg")
    urls.append(None)  # BirdNET-Go's own copy (320 px)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for url in urls:
            try:
                if url:
                    r = await client.get(url)
                else:
                    r = await bng.client().get(f"/media/image/{sci}")
                if (r.status_code == 200 and r.headers.get("content-type", "").startswith("image/jpeg")
                        and 0 < len(r.content) <= MAX_BYTES):
                    return r.content
                log.info("photo %s %s: HTTP %s %s", sci, size, r.status_code, r.headers.get("content-type"))
            except httpx.HTTPError as ex:
                log.info("photo %s %s: %s", sci, size, ex)
    return None
