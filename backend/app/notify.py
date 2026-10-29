"""Discord posts: a new yard bird, a bird back after a long absence, and the weekly report.

Messages use Discord's Components V2 layout (IS_COMPONENTS_V2, `?with_components=true`, which a
plain channel webhook may use for non-interactive components and link buttons): a container with
the bird's colors, sections with photo thumbnails, galleries of public photos and spectrograms,
and link buttons into the public site. Posts in quiet hours go out silent. The `sent` table makes
each post happen once, across restarts.
"""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta

import httpx

from . import config, db, stats
from .db import VISIBLE

log = logging.getLogger("birbtrack.notify")
FINCH_RED, VERDIN_GOLD, NIGHT = 0xB42E47, 0xC99410, 0x1B2150
COMPONENTS_V2, SILENT, NO_EMBEDS = 1 << 15, 1 << 12, 1 << 2
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def url(path: str) -> str:
    return f"{config.PUBLIC_URL}{path}"


def quiet(now: datetime) -> bool:
    h = now.hour
    if config.QUIET_START > config.QUIET_END:
        return h >= config.QUIET_START or h < config.QUIET_END
    return config.QUIET_START <= h < config.QUIET_END


# ---- Components V2 building blocks ----

def text(content: str) -> dict:
    return {"type": 10, "content": content}


def section(lines: list[str], thumb_url: str | None = None, alt: str = "") -> dict:
    out = {"type": 9, "components": [text("\n".join(lines))]}
    if thumb_url:
        out["accessory"] = {"type": 11, "media": {"url": thumb_url}, "description": alt[:1024]}
    else:  # a section needs an accessory; fall back to plain text
        return text("\n".join(lines))
    return out


def gallery(items: list[tuple[str, str]]) -> dict:
    return {"type": 12, "items": [{"media": {"url": u}, "description": d[:1024]} for u, d in items[:10]]}


def divider(big: bool = False) -> dict:
    return {"type": 14, "divider": True, "spacing": 2 if big else 1}


def buttons(links: list[tuple[str, str]]) -> dict:
    return {"type": 1, "components": [{"type": 2, "style": 5, "label": label[:80], "url": href}
                                      for label, href in links[:5]]}


def container(accent: int, children: list) -> dict:
    return {"type": 17, "accent_color": accent, "components": [c for c in children if c]}


def photo_url(slug: str, size: int = 900) -> str:
    return url(f"/media/bird/{slug}-{size}.jpg")


async def post(components: list) -> bool:
    if not config.DISCORD_WEBHOOK:
        log.warning("no Discord webhook configured; not posting")
        return False
    flags = COMPONENTS_V2 | NO_EMBEDS | (SILENT if quiet(datetime.now(config.TZ)) else 0)
    payload = {"username": config.DISCORD_NAME, "flags": flags, "allowed_mentions": {"parse": []},
               "components": components}
    async with httpx.AsyncClient(timeout=20) as client:
        for _ in range(3):
            r = await client.post(config.DISCORD_WEBHOOK, params={"wait": "true", "with_components": "true"},
                                  json=payload)
            if r.status_code == 429:
                await asyncio.sleep(min(float(r.json().get("retry_after", 2)), 30))
                continue
            if r.status_code >= 400:
                log.error("Discord said %s: %s", r.status_code, r.text[:500])
                return False
            return True
    return False


# ---- a new yard bird / back after a long absence ----

def detection_message(row: dict, kind: str, days_away: int | None = None) -> list:
    d = stats.detection(row["id"]) or {}
    common, slug = d.get("common", row["common"]), d.get("slug", db.slugify(row["common"]))
    has_photo = d.get("photo", False)
    if kind == "lifer":
        n = stats.yard_number(row["sci"])
        head, accent = "New yard bird", FINCH_RED
        tail = f"Species No. {n} on the yard list" if n else None
    else:
        head, accent = f"Back after {days_away} days", VERDIN_GOLD
        tail = None
    lines = [f"-# {head}", f"## {common}", f"*{row['sci']}*"]
    if d.get("fact"):
        lines.append(f"\n{d['fact']}")
    when = f"**{stats.fmt_time(row['hms'])}**, {round(row['confidence'] * 100)}% sure"
    media = []
    if has_photo:
        media.append((photo_url(slug), common))
    if row.get("clip"):
        media.append((url(f"/media/spectro/{row['id']}.png"), f"Spectrogram of the {common} call"))
    return [container(accent, [
        section(lines, photo_url(slug, 320) if has_photo else None, common),
        gallery(media) if media else None,
        text(when + (f"\n-# {tail}" if tail else "")),
        buttons([("Listen", url(f"/d/{row['id']}")), (common, url(f"/bird/{slug}")), ("Today", url("/"))]),
    ])]


async def on_detection(row: dict):
    """Listener for new live detections (sync.listeners)."""
    stats.invalidate()

    def history():
        return db.conn().execute(f"SELECT MAX(ts) FROM detections WHERE sci = ? AND {VISIBLE} "
                                 f"AND (ts < ? OR (ts = ? AND id < ?))",
                                 (row["sci"], row["ts"], row["ts"], row["id"])).fetchone()[0]
    prev = await asyncio.to_thread(history)
    if prev is None:
        kind, key, days = "lifer", row["sci"], None
    else:
        days = (row["ts"] - prev) // 86400
        if days < config.COMEBACK_DAYS:
            return
        if await asyncio.to_thread(stats.across_outage, prev, row["ts"]):
            log.info("%s back after %d days, the station was off for part of it: no post", row["common"], days)
            return
        kind, key = "comeback", f"{row['sci']}:{row['day']}"
    if kind not in config.NOTIFY:
        return
    if not await asyncio.to_thread(db.mark_sent, kind, key, int(time.time())):
        return
    ok = await post(await asyncio.to_thread(detection_message, row, kind, days))
    log.info("%s post for %s (%s): %s", kind, row["common"], row["id"], "sent" if ok else "FAILED")
    if not ok:
        await asyncio.to_thread(unmark, kind, key)


def unmark(kind: str, key: str):
    c = db.conn()
    c.execute("DELETE FROM sent WHERE kind = ? AND key = ?", (kind, key))
    c.commit()


# ---- the weekly report ----

def bar(value: int, top: int, width: int = 14) -> str:
    filled = round(value / top * width) if top else 0
    return "█" * filled + "░" * (width - filled)


def change(pct) -> str:
    return "" if pct is None else f"  {'+' if pct >= 0 else '−'}{abs(pct)}%"


def weekly_message(key: str) -> list:
    w = stats.week(key)
    start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
    link = lambda s: f"[{s['common']}]({url('/bird/' + s['slug'])})"
    span = f"{start.strftime('%b %-d')} to {end.strftime('%b %-d, %Y')}"
    top = w["species"][0] if w["species"] else None

    head = section(
        ["-# birbTrack weekly", f"# Week {w['number']}", span, "",
         f"**{w['total']:,}** calls{change(w['total_change'])}",
         f"**{w['species_count']}** species{change(w['species_change'])}"],
        photo_url(top["slug"], 320) if top and top["photo"] else None, top["common"] if top else "")

    stars = [s for s in w["species"] if s["photo"]][:4]
    hero = gallery([(photo_url(s["slug"]), f"{s['common']}, {s['count']:,} calls") for s in stars]) if stars else None

    peak = max((d["count"] for d in w["daily"]), default=0)
    days = "\n".join(f"{DAY_ABBR[date.fromisoformat(d['day']).weekday()]} {bar(d['count'], peak)} {d['count']:>5,}"
                     for d in w["daily"])
    daily_md = f"### Every day\n```\n{days}\n```"
    if w["peak_hour"] is not None:
        daily_md += f"\n-# Peak hour {stats.fmt_time('%02d:00:00' % w['peak_hour'])}"
    daily = text(daily_md)

    ranks = "\n".join(f"`{i:>2}` {link(s)}  **{s['count']:,}**" for i, s in enumerate(w["species"][:10], 1))
    top10 = text(f"### Top 10\n{ranks}")

    awards = []
    for label, k, line in (
            ("Early bird", "early_bird", lambda a: f"{stats.fmt_time(a['time'])} on {date.fromisoformat(a['day']).strftime('%A')}"),
            ("Night owl", "night_owl", lambda a: f"{stats.fmt_time(a['time'])} on {date.fromisoformat(a['day']).strftime('%A')}")):
        a = w[k]
        if a:
            awards.append(section([f"-# {label}", f"### {link(a)}", line(a)],
                                  photo_url(a["slug"], 320) if a.get("photo") else None, a["common"]))
    if w["most_loyal"]:
        m = w["most_loyal"]
        m_card = stats.card(m["sci"])
        awards.append(section(["-# Most loyal", f"### {link(m_card)}", f"{m['days']} of 7 days, {m['count']:,} calls"],
                              photo_url(m_card["slug"], 320) if m_card["photo"] else None, m_card["common"]))

    news = []
    if w["lifers"]:
        news.append("**New yard birds**  " + ", ".join(link(s) for s in w["lifers"][:8]))
    if w["new_vs_last_week"]:
        news.append("**New this week**  " + ", ".join(link(s) for s in w["new_vs_last_week"][:8]))
    if w["returning"]:
        news.append("**Back**  " + ", ".join(f"{link(s)} ({s['days_away']}d)" for s in w["returning"][:6]))

    spot = None
    if w["spotlight"]:
        sp = w["spotlight"]
        spot = section(["-# Spotlight", f"### {link(sp)}", f"*{sp['fact']}*"],
                       photo_url(sp["slug"], 320) if sp["photo"] else None, sp["common"])

    notes = []
    if w["busiest"]:
        notes.append(f"Busiest {DAY_ABBR[date.fromisoformat(w['busiest']['day']).weekday()]} ({w['busiest']['count']:,})")
        notes.append(f"quietest {DAY_ABBR[date.fromisoformat(w['quietest']['day']).weekday()]} ({w['quietest']['count']:,})")
    notes.append(f"all time {w['lifetime']['detections']:,} calls from {w['lifetime']['species']} species")

    return [container(NIGHT, [
        head, hero, divider(), daily, top10, divider(),
        *awards,
        divider() if news or spot else None,
        text("\n".join(news)) if news else None,
        spot,
        text("-# " + ", ".join(notes)),
        buttons([(f"Week {w['number']}", url(f"/week/{key}")), ("Yard list", url("/birds")), ("Today", url("/"))]),
    ])]


def due_week(now: datetime) -> tuple[str, datetime]:
    """The week the most recent scheduled run reports on, and when that run was."""
    run = now.replace(hour=config.WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    run -= timedelta(days=(run.weekday() - config.WEEKLY_DAY) % 7)
    if run > now:
        run -= timedelta(days=7)
    return stats.week_key((run - timedelta(days=7)).date()), run


async def send_weekly(key: str, force: bool = False) -> bool:
    if not force and not await asyncio.to_thread(db.mark_sent, "weekly", key, int(time.time())):
        return False
    if not force and (await asyncio.to_thread(stats.week, key))["total"] == 0:
        log.info("weekly report %s: nothing heard all week, not posting", key)
        return False
    ok = await post(await asyncio.to_thread(weekly_message, key))
    log.info("weekly report %s: %s", key, "sent" if ok else "FAILED")
    if not ok and not force:
        await asyncio.to_thread(unmark, "weekly", key)
    return ok


async def weekly_loop():
    """Monday 01:00 by default. Catches up within 12 h after downtime."""
    while True:
        now = datetime.now(config.TZ)
        key, run = due_week(now)
        if "weekly" in config.NOTIFY and now - run < timedelta(hours=12):
            if not await asyncio.to_thread(db.was_sent, "weekly", key):
                try:
                    await send_weekly(key)
                except Exception:
                    log.exception("weekly report %s", key)
        nxt = run + timedelta(days=7)
        await asyncio.sleep(max(30, min(3600, (nxt - now).total_seconds() + 5)))
