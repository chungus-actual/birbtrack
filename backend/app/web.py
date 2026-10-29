"""birbTrack's HTTP surface: read-only JSON, proxied media, a live feed, and the page shell.

Built to face the internet behind a reverse proxy: GET/HEAD only, strict CSP, a per-client rate limit,
media only for detections the mirror knows, and no coordinates anywhere.
"""

import asyncio
import html
import ipaddress
import json
import logging
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders

import base64

from . import bng, config, db, images, info, notify, place, ranges, stats, sync

log = logging.getLogger("birbtrack.web")

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
SECURITY_HEADERS = [
    ("content-security-policy", CSP),
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    ("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()"),
    ("cross-origin-opener-policy", "same-origin"),
    ("x-frame-options", "DENY"),
]
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK_RX = re.compile(r"^\d{4}-W\d{2}$")
SLUG_RX = re.compile(r"^[a-z0-9-]{1,80}$")
API_CACHE = {"cache-control": "public, max-age=10"}


def client_ip(scope) -> str:
    peer = (scope.get("client") or ("0.0.0.0", 0))[0]
    try:
        trusted = any(ipaddress.ip_address(peer) in n for n in config.TRUSTED_PROXIES)
    except ValueError:
        trusted = False
    if trusted:
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        for h in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
            if headers.get(h):
                return headers[h].split(",")[0].strip()[:64]
    return peer


class Guard:
    """Security headers on every response, GET/HEAD only, and a token bucket per client."""

    def __init__(self, app):
        self.app = app
        self.buckets: dict[str, tuple[float, float]] = {}

    def allow(self, ip: str) -> bool:
        rate, cap = config.RATE_PER_MIN / 60.0, float(config.RATE_PER_MIN)
        now = time.monotonic()
        tokens, last = self.buckets.get(ip, (cap, now))
        tokens = min(cap, tokens + (now - last) * rate)
        if len(self.buckets) > 20000:
            self.buckets.clear()
        if tokens < 1:
            self.buckets[ip] = (tokens, now)
            return False
        self.buckets[ip] = (tokens - 1, now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_secured(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for k, v in SECURITY_HEADERS:
                    if k not in headers:
                        headers[k] = v
            await send(message)

        scope["birb_ip"] = ip = client_ip(scope)
        if scope["method"] not in ("GET", "HEAD"):
            return await JSONResponse({"error": "This site is read-only."}, 405,
                                      headers={"allow": "GET, HEAD"})(scope, receive, send_secured)
        if not scope["path"].startswith("/assets/") and not self.allow(ip):
            return await JSONResponse({"error": "Too many requests. Wait a minute and reload."}, 429,
                                      headers={"retry-after": "30"})(scope, receive, send_secured)
        await self.app(scope, receive, send_secured)


class Hub:
    """Fan new detections out to every open /api/live stream."""

    def __init__(self):
        self.queues: set[asyncio.Queue] = set()
        self.per_ip: Counter = Counter()

    async def publish(self, row: dict):
        stats.invalidate()
        payload = json.dumps(await asyncio.to_thread(stats.detection_brief, row))
        for q in list(self.queues):
            if q.full():
                continue
            q.put_nowait(payload)


hub = Hub()


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db.init()
    ranges.init()
    info.init()
    sync.listeners[:] = [hub.publish, notify.on_detection]

    async def after_backfill(job):
        while not sync.state["backfilled"]:
            await asyncio.sleep(5)
        await job()

    await images.load()
    tasks = [asyncio.create_task(sync.run()), asyncio.create_task(notify.weekly_loop()),
             asyncio.create_task(place.resolve()), asyncio.create_task(images.keep_fresh()),
             asyncio.create_task(after_backfill(ranges.keep_fresh)), asyncio.create_task(after_backfill(info.keep_fresh))]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(Guard)


def check_date(d: str) -> str:
    if d == "today":
        return stats.today().isoformat()
    if not DATE_RX.match(d):
        raise HTTPException(404)
    try:
        date.fromisoformat(d)
    except ValueError:
        raise HTTPException(404)
    return d


def check_week(k: str) -> str:
    if k in ("this", "current"):
        return stats.week_key(stats.today())
    if not WEEK_RX.match(k):
        raise HTTPException(404)
    try:
        stats.week_bounds(k)
    except ValueError:
        raise HTTPException(404)
    return k


def json_response(data, status=200):
    if data is None:
        raise HTTPException(404)
    return JSONResponse(data, status, headers=API_CACHE)


@app.get("/healthz")
def healthz():
    n = db.conn().execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    return {"ok": True, "detections": n, "backfilled": sync.state["backfilled"], "stream": sync.state["stream"],
            "last_sync_s": int(time.time() - sync.state["last_sync"]) if sync.state["last_sync"] else None,
            "live_clients": len(hub.queues)}


@app.get("/api/overview")
def api_overview():
    return json_response(stats.overview())


@app.get("/api/day/{d}")
def api_day(d: str):
    return json_response(stats.day(check_date(d)))


@app.get("/api/species")
def api_species():
    return json_response(stats.species_list())


@app.get("/api/species/{slug}")
def api_species_detail(slug: str):
    if not SLUG_RX.match(slug):
        raise HTTPException(404)
    return json_response(stats.species_detail(slug))


@app.get("/api/map")
def api_map():
    """The region's basemap, its sample points and the yard, all in map units."""
    g = ranges.GRID
    if g is None:
        return JSONResponse({"building": True}, 503, headers={"cache-control": "no-store"})
    return JSONResponse({k: g[k] for k in ("name", "w", "h", "land", "lakes", "borders", "spacing")}
                        | {"points": [[p[2], p[3]] for p in g["points"]], "home": ranges.project(config.LAT, config.LON)},
                        headers={"cache-control": "public, max-age=86400"})


@app.get("/api/species/{slug}/range")
def api_species_range(slug: str):
    if not SLUG_RX.match(slug):
        raise HTTPException(404)
    row = db.conn().execute("SELECT sci FROM species WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise HTTPException(404)
    months = ranges.months(row[0])
    if not months:
        return JSONResponse({"building": ranges.state["building"], "done": ranges.state["done"],
                             "total": ranges.state["total"]}, 202, headers={"cache-control": "no-store"})
    return JSONResponse({"months": [base64.b64encode(m).decode() for m in months]},
                        headers={"cache-control": "public, max-age=3600"})


@app.get("/api/week/{key}")
def api_week(key: str):
    return json_response(stats.week(check_week(key)))


@app.get("/api/detection/{det_id}")
def api_detection(det_id: int):
    return json_response(stats.detection(det_id))


@app.get("/api/recent")
def api_recent(limit: int = 20):
    return json_response(stats.recent(max(1, min(limit, 50))))


@app.get("/api/live")
async def api_live(request: Request):
    ip = request.scope.get("birb_ip", "?")
    if len(hub.queues) >= config.LIVE_MAX or hub.per_ip[ip] >= config.LIVE_PER_IP:
        return JSONResponse({"error": "Too many live connections."}, 503, headers={"retry-after": "60"})
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    hub.queues.add(q)
    hub.per_ip[ip] += 1

    async def events():
        try:
            yield "retry: 10000\n\n"
            while not await request.is_disconnected():
                try:
                    item = await asyncio.wait_for(q.get(), 20)
                    yield f"event: detection\ndata: {item}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.queues.discard(q)
            hub.per_ip[ip] -= 1
            if hub.per_ip[ip] <= 0:
                del hub.per_ip[ip]

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


def visible_clip(det_id: int) -> bool:
    r = db.conn().execute("SELECT clip FROM detections WHERE id = ? AND verified != 'false_positive'",
                          (det_id,)).fetchone()
    return bool(r and r[0])


@app.get("/media/clip/{det_id}.mp3")
async def media_clip(det_id: int, request: Request):
    if not await asyncio.to_thread(visible_clip, det_id):
        raise HTTPException(404)
    headers = {"range": request.headers["range"]} if "range" in request.headers else {}
    r = await bng.client().send(bng.client().build_request("GET", f"/audio/{det_id}", headers=headers), stream=True)
    if r.status_code not in (200, 206):
        await r.aclose()
        raise HTTPException(404)
    out = {k: r.headers[k] for k in ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
           if k in r.headers}
    out["cache-control"] = "public, max-age=604800"
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, media_type="audio/mpeg", headers=out,
                             background=BackgroundTask(r.aclose))


_spectro_gate = asyncio.Semaphore(2)
_spectro_locks: dict[int, asyncio.Lock] = {}


@app.get("/media/spectro/{det_id}.png")
async def media_spectro(det_id: int):
    if not await asyncio.to_thread(visible_clip, det_id):
        raise HTTPException(404)
    path = config.DATA / "spectro" / f"{det_id}.png"
    if not path.exists():
        lock = _spectro_locks.setdefault(det_id, asyncio.Lock())
        async with lock, _spectro_gate:
            if not path.exists():
                r = await bng.client().get(f"/spectrogram/{det_id}", params={"width": 1200})
                if (r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/png")
                        or len(r.content) > 6 * 1024 * 1024):
                    raise HTTPException(404)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(path)
        _spectro_locks.pop(det_id, None)
    return FileResponse(path, media_type="image/png", headers={"cache-control": "public, max-age=2592000"})


@app.get("/media/bird/{name}.jpg")
async def media_bird(name: str):
    slug, _, size = name.rpartition("-")
    if not SLUG_RX.match(slug or "-") or size not in ("320", "900"):
        raise HTTPException(404)
    row = await asyncio.to_thread(lambda: db.conn().execute("SELECT sci FROM species WHERE slug = ?",
                                                            (slug,)).fetchone())
    if not row:
        raise HTTPException(404)
    path = await images.photo(slug, row[0], int(size))
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"cache-control": "public, max-age=2592000"})


# ---- the page shell, with link-preview tags per page (Discord unfurls these) ----

_index = {"mtime": 0.0, "html": ""}


def index_html() -> str:
    p = config.STATIC / "index.html"
    m = p.stat().st_mtime
    if m != _index["mtime"]:
        _index.update(mtime=m, html=p.read_text(encoding="utf-8"))
    return _index["html"]


def page_meta(path: str):
    """(status, title, description, image path) for a page, or None for an unknown path."""
    parts = path.strip("/").split("/")
    site = config.SITE
    if parts == [""]:
        o = stats.overview()
        if o["today_total"]:
            desc = f"{o['today_species']} species and {o['today_total']:,} calls heard in {config.PLACE} so far today."
        else:
            desc = f"{config.PLACE[:1].upper()}{config.PLACE[1:]}, listening for birds. {o['lifetime']['species']} species heard so far."
        return 200, site, desc, None
    if parts == ["birds"]:
        n = stats.species_list()["total"]
        return 200, f"The yard list | {site}", f"All {n} species heard in {config.PLACE}.", None
    if len(parts) == 2 and parts[0] == "bird" and SLUG_RX.match(parts[1]):
        s = stats.species_detail(parts[1])
        if s:
            desc = s["fact"] or f"Heard {s['count']:,} times since {_nice_date(s['first'])}."
            return 200, f"{s['common']} | {site}", desc, f"/media/bird/{s['slug']}-900.jpg" if s["photo"] else None
    if len(parts) == 2 and parts[0] == "day" and DATE_RX.match(parts[1]):
        try:
            d = stats.day(check_date(parts[1]))
            return 200, f"{_nice_date(d['date'])} | {site}", \
                f"{d['species_count']} species, {d['total']:,} calls on {_nice_date(d['date'])}.", None
        except HTTPException:
            pass
    if len(parts) == 2 and parts[0] == "week" and (WEEK_RX.match(parts[1]) or parts[1] == "this"):
        try:
            w = stats.week(check_week(parts[1]))
            img = f"/media/bird/{w['species'][0]['slug']}-900.jpg" if w["species"] else None
            return 200, f"Week {w['number']} | {site}", \
                f"{w['total']:,} calls from {w['species_count']} species, {_nice_date(w['start'])} to {_nice_date(w['end'])}.", img
        except HTTPException:
            pass
    if len(parts) == 2 and parts[0] == "d" and parts[1].isdigit() and len(parts[1]) < 12:
        d = stats.detection(int(parts[1]))
        if d:
            title = f"{d['common']} at {stats.fmt_time(d['time'])}, {_nice_date(d['day'])}"
            return 200, f"{title} | {site}", d["fact"] or f"{round(d['confidence'] * 100)}% confident.", \
                f"/media/bird/{d['slug']}-900.jpg" if d["photo"] else None
    return None


def _nice_date(d: str) -> str:
    return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d, %Y")


def render_shell(path: str) -> HTMLResponse:
    meta = page_meta(path)
    status, title, desc, image = meta or (404, f"Not found | {config.SITE}", "No such page on birbTrack.", None)
    e = lambda s: html.escape(s, quote=True)
    tags = [f"<title>{e(title)}</title>",
            f'<meta name="description" content="{e(desc)}">',
            f'<meta property="og:site_name" content="{config.SITE}">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta property="og:url" content="{e(config.PUBLIC_URL + "/" + path.strip("/"))}">',
            '<meta property="og:type" content="website">']
    if image:
        tags += [f'<meta property="og:image" content="{e(config.PUBLIC_URL + image)}">',
                 '<meta name="twitter:card" content="summary_large_image">']
    doc = re.sub(r"<title>.*?</title>", "\n    ".join(tags), index_html(), count=1, flags=re.S)
    return HTMLResponse(doc, status, headers={"cache-control": "no-cache, no-transform"})


@app.get("/{path:path}")
def shell(path: str):
    if path.startswith(("api/", "media/")):
        raise HTTPException(404)
    if path and "." in path.rsplit("/", 1)[-1]:
        f = (config.STATIC / path).resolve()
        if f.is_file() and config.STATIC.resolve() in f.parents:
            immutable = path.startswith("assets/")
            return FileResponse(f, headers={"cache-control": "public, max-age=31536000, immutable" if immutable
                                            else "public, max-age=3600"})
        raise HTTPException(404)
    return render_shell(path)
