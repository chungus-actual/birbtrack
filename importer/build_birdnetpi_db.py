#!/usr/bin/env python3
"""Rebuild a BirdNET-Pi birds.db for BirdNET-Go's importer from what survives on a failing card.

When birds.db is corrupt ("database disk image is malformed"), BirdDB.txt (its text twin, with no
File_Name column) and the extracted mp3 clips usually survive. This writes a fresh birds.db with the
`detections` table BirdNET-Go reads (internal/imports/birdnetpi/source.go: rowid, Date, Time,
Sci_Name, Com_Name, Confidence, Lat, Lon, Cutoff, Sens, File_Name):

  * every clean BirdDB.txt row, with File_Name filled in when its clip exists
    (Extracted/By_Date/<Date>/<Com_Name, spaces->_ and ' dropped>/<file>);
  * every clip with no BirdDB.txt row (a corrupt stretch, or days after the text log stopped) as a
    detection rebuilt from its filename: <Com>-<pct>-<date>-birdnet-<time>.mp3 (confidence only to
    the whole percent; the scientific name comes from the BirdDB.txt rows).

Rows rebuilt from clips take the station settings from the flags (BirdNET-Pi's birdnet.conf has them).

usage: build_birdnetpi_db.py BirdDB.txt By_Date/ out/birds.db --lat 0.0 --lon 0.0
                             [--cutoff 0.7] [--sens 1.25] [--overlap 0.0]
"""
import argparse
import collections
import re
import sqlite3
from pathlib import Path

ROW = re.compile(r"^\d{4}-\d{2}-\d{2};\d{2}:\d{2}:\d{2};[^;]+;[^;]+;0?\.\d+;")
CLIP = re.compile(r"^(?P<com>.+)-(?P<pct>\d{1,3})-(?P<date>\d{4}-\d{2}-\d{2})-birdnet-(?:.*-)?"
                  r"(?P<time>\d{2}:\d{2}:\d{2})\.mp3$")


def dirname(com):
    return com.replace(" ", "_").replace("'", "")


def week(date):
    # BirdNET-Pi's 48-week calendar: 4 weeks a month
    y, m, d = map(int, date.split("-"))
    return (m - 1) * 4 + min(4, (d - 1) // 7 + 1)


def main(birddb, by_date, out, lat, lon, cutoff, sens, overlap):
    rows, bad = [], 0
    for i, line in enumerate(open(birddb, encoding="utf-8", errors="replace")):
        line = line.rstrip("\n")
        if i == 0:
            continue
        p = line.split(";")
        if ROW.match(line) and len(p) == 11:
            rows.append(p)
        else:
            bad += 1

    names = {}  # clip dir name -> (com, sci)
    for r in rows:
        names[dirname(r[3])] = (r[3], r[2])

    clips = {}  # (date, dir, time) -> filename
    unparsed = 0
    for f in Path(by_date).glob("*/*/*.mp3"):
        m = CLIP.match(f.name)
        if not m or m["date"] != f.parent.parent.name:
            unparsed += 1
            continue
        clips[(m["date"], f.parent.name, m["time"])] = (f.name, int(m["pct"]))

    used, out_rows = set(), []
    for r in rows:
        key = (r[0], dirname(r[3]), r[1])
        fn = ""
        if key in clips:
            fn = clips[key][0]
            used.add(key)
        out_rows.append((r[0], r[1], r[2], r[3], float(r[4]), float(r[5]), float(r[6]),
                         float(r[7]), int(r[8]), float(r[9]), float(r[10]), fn))

    orphan_species = collections.Counter()
    from_clips = 0
    for key, (fn, pct) in clips.items():
        if key in used:
            continue
        date, d, time = key
        if d not in names:
            orphan_species[d] += 1
            continue
        com, sci = names[d]
        out_rows.append((date, time, sci, com, pct / 100, lat, lon, cutoff, week(date), sens,
                         overlap, fn))
        from_clips += 1

    out_rows.sort(key=lambda r: (r[0], r[1]))
    Path(out).unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.execute("""CREATE TABLE detections (Date DATE, Time TIME, Sci_Name VARCHAR(100) NOT NULL,
        Com_Name VARCHAR(100) NOT NULL, Confidence FLOAT, Lat FLOAT, Lon FLOAT, Cutoff FLOAT,
        Week INT, Sens FLOAT, Overlap FLOAT, File_Name VARCHAR(100) NOT NULL)""")
    db.executemany("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out_rows)
    db.commit()
    with_clip = sum(1 for r in out_rows if r[11])
    days = db.execute("SELECT MIN(Date), MAX(Date), COUNT(DISTINCT Date), COUNT(DISTINCT Sci_Name) "
                      "FROM detections").fetchone()
    db.close()
    print(f"BirdDB.txt rows {len(rows)} (bad lines {bad}); clips {len(clips)} (unparsed {unparsed})")
    print(f"rows matched to a clip {len(used)}; clip-only detections added {from_clips}")
    print(f"clips of species never in BirdDB.txt (skipped) {sum(orphan_species.values())} "
          f"{dict(orphan_species.most_common(8))}")
    print(f"wrote {out}: {len(out_rows)} detections, {with_clip} with a clip, "
          f"{days[0]} -> {days[1]}, {days[2]} days, {days[3]} species")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("birddb")
    ap.add_argument("by_date")
    ap.add_argument("out")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--cutoff", type=float, default=0.7)
    ap.add_argument("--sens", type=float, default=1.25)
    ap.add_argument("--overlap", type=float, default=0.0)
    a = ap.parse_args()
    main(a.birddb, a.by_date, a.out, a.lat, a.lon, a.cutoff, a.sens, a.overlap)
