"""birbTrack's own SQLite mirror of BirdNET-Go's detections (no coordinates, ever).

One connection per thread (FastAPI runs sync endpoints in a pool); WAL so the sync task
writes while pages read.
"""

import re
import sqlite3
import threading
import unicodedata

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY,            -- BirdNET-Go detection id
    ts INTEGER NOT NULL,               -- unix seconds
    day TEXT NOT NULL,                 -- local date
    hms TEXT NOT NULL,                 -- local time
    sci TEXT NOT NULL,
    common TEXT NOT NULL,
    code TEXT,
    confidence REAL NOT NULL,
    clip INTEGER NOT NULL DEFAULT 0,
    verified TEXT NOT NULL DEFAULT 'unverified',
    seen_at INTEGER NOT NULL           -- when birbTrack first saw it
);
CREATE INDEX IF NOT EXISTS ix_det_day ON detections(day);
CREATE INDEX IF NOT EXISTS ix_det_sci_ts ON detections(sci, ts);
CREATE INDEX IF NOT EXISTS ix_det_ts ON detections(ts);

CREATE TABLE IF NOT EXISTS species (
    sci TEXT PRIMARY KEY,
    common TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    code TEXT,
    family TEXT,
    family_common TEXT,
    ord TEXT,
    rarity TEXT
);

CREATE TABLE IF NOT EXISTS sent (       -- one row per Discord post, so nothing posts twice
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    at INTEGER NOT NULL,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

# rows a visitor may see: BirdNET-Go reviews can mark a detection false positive
VISIBLE = "verified != 'false_positive'"

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        config.DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(config.DB_PATH, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


def init():
    conn().executescript(SCHEMA)


def slugify(common: str) -> str:
    s = unicodedata.normalize("NFKD", common).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def get_meta(k, default=None):
    row = conn().execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
    return row[0] if row else default


def set_meta(k, v):
    c = conn()
    c.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))
    c.commit()


def upsert(rows, now):
    """Insert or refresh detections; returns the ids that were new to birbTrack."""
    c = conn()
    ids = [r["id"] for r in rows]
    known = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        known.update(x[0] for x in c.execute(
            f"SELECT id FROM detections WHERE id IN ({','.join('?' * len(chunk))})", chunk))
    c.executemany("""
        INSERT INTO detections (id, ts, day, hms, sci, common, code, confidence, clip, verified, seen_at)
        VALUES (:id, :ts, :day, :hms, :sci, :common, :code, :confidence, :clip, :verified, :seen_at)
        ON CONFLICT(id) DO UPDATE SET ts = excluded.ts, day = excluded.day, hms = excluded.hms,
            sci = excluded.sci, common = excluded.common, code = excluded.code,
            confidence = excluded.confidence, clip = excluded.clip, verified = excluded.verified
    """, [dict(r, seen_at=now) for r in rows])
    for r in rows:
        ensure_species(c, r["sci"], r["common"], r.get("code"))
    c.commit()
    return [i for i in ids if i not in known]


def ensure_species(c, sci, common, code=None):
    if c.execute("SELECT 1 FROM species WHERE sci = ?", (sci,)).fetchone():
        return
    slug = slugify(common) or slugify(sci)
    if c.execute("SELECT 1 FROM species WHERE slug = ?", (slug,)).fetchone():
        slug = f"{slug}-{slugify(sci)}"
    c.execute("INSERT INTO species (sci, common, slug, code) VALUES (?, ?, ?, ?)", (sci, common, slug, code))


def delete_missing(day, remote_ids):
    """Drop local rows for `day` that BirdNET-Go no longer has (deleted in its UI)."""
    c = conn()
    local = {r[0] for r in c.execute("SELECT id FROM detections WHERE day = ?", (day,))}
    gone = local - set(remote_ids)
    if gone:
        c.executemany("DELETE FROM detections WHERE id = ?", [(i,) for i in gone])
        c.commit()
    return len(gone)


def mark_sent(kind, key, at):
    c = conn()
    cur = c.execute("INSERT OR IGNORE INTO sent (kind, key, at) VALUES (?, ?, ?)", (kind, key, at))
    c.commit()
    return cur.rowcount == 1


def was_sent(kind, key):
    return conn().execute("SELECT 1 FROM sent WHERE kind = ? AND key = ?", (kind, key)).fetchone() is not None
