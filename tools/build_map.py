#!/usr/bin/env python3
"""Build the range-map regions from Natural Earth 110m (public domain).

usage: build_map.py <dir with ne_110m_land/lakes/admin_0_boundary_lines_land .geojson> <birbtrack repo> [region ...]

For each region (all of them by default) writes backend/app/maps/<region>.json:
  name, box          the region and its lon/lat box (the server picks the one holding the station)
  w, h, land, lakes, borders
                     SVG path data in an Equal Earth projection centred on the region, 1000 units wide
  central, k, minx, miny
                     the projection constants, so the server can place the station on the same map
  step, spacing, points
                     land points every `step` degrees as [lat, lon, x, y], and how far apart
                     neighbours sit on the map (the heat blobs are sized from it)

Every point costs BirdNET-Go 12 calls (one per month) when the ranges are built, so the steps keep
each region near 600 to 1,000 points.
"""
import json
import math
import sys
from pathlib import Path

WIDTH = 1000.0
A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
#            name                         lon0    lon1   lat0  lat1  central  step
REGIONS = {
    "americas": ("the Americas",            -170.0, -25.0, -57.0, 75.0, -95.0, 2.5),
    "europe":   ("Europe",                  -25.0,  45.0,  30.0,  72.0,  10.0, 1.5),
    "africa":   ("Africa",                  -20.0,  55.0, -36.0,  38.0,  17.0, 2.0),
    "asia":     ("Asia",                     25.0, 150.0, -11.0,  78.0,  90.0, 3.0),
    "oceania":  ("Australia and New Zealand", 110.0, 180.0, -48.0,  0.0, 145.0, 1.0),
}


def equal_earth(lon, lat, central):
    lam = math.radians(lon - central)
    th = math.asin(math.sqrt(3) / 2 * math.sin(math.radians(lat)))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(th) / (3 * (9 * A4 * t6 * t2 + 7 * A3 * t6 + 3 * A2 * t2 + A1))
    y = A4 * t6 * t2 * th + A3 * t6 * th + A2 * t2 * th + A1 * th
    return x, -y


def clip(ring, edges):
    """Sutherland-Hodgman against the lon/lat box."""
    for inside, cross in edges:
        out = []
        for i, cur in enumerate(ring):
            prev = ring[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        ring = out
        if not ring:
            break
    return ring


def lerp_lon(a, b, lon):
    t = (lon - a[0]) / (b[0] - a[0])
    return [lon, a[1] + t * (b[1] - a[1])]


def lerp_lat(a, b, lat):
    t = (lat - a[1]) / (b[1] - a[1])
    return [a[0] + t * (b[0] - a[0]), lat]


def rings(geojson, polygons=True):
    for f in geojson["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            yield from ([r] for r in g["coordinates"][:1]) if polygons else ()
        elif g["type"] == "MultiPolygon":
            for poly in g["coordinates"]:
                yield [poly[0]]
        elif g["type"] == "LineString":
            yield [g["coordinates"]]
        elif g["type"] == "MultiLineString":
            for line in g["coordinates"]:
                yield [line]


def inside_ring(lon, lat, ring):
    hit = False
    for i in range(len(ring)):
        x1, y1 = ring[i - 1]
        x2, y2 = ring[i]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def build(key, src):
    name, lon0, lon1, lat0, lat1, central, step = REGIONS[key]
    edges = [
        (lambda p: p[0] >= lon0, lambda a, b: lerp_lon(a, b, lon0)),
        (lambda p: p[0] <= lon1, lambda a, b: lerp_lon(a, b, lon1)),
        (lambda p: p[1] >= lat0, lambda a, b: lerp_lat(a, b, lat0)),
        (lambda p: p[1] <= lat1, lambda a, b: lerp_lat(a, b, lat1)),
    ]
    land_rings = [c for r in rings(src["land"]) for c in [clip(r[0], edges)] if len(c) >= 3]
    lake_rings = [c for r in rings(src["lakes"]) for c in [clip(r[0], edges)] if len(c) >= 3]
    border_lines = []
    for r in rings(src["borders"], polygons=False):
        line = [p for p in r[0] if lon0 <= p[0] <= lon1 and lat0 <= p[1] <= lat1]
        if len(line) >= 2:
            border_lines.append(line)

    pts = [equal_earth(lon, lat, central) for ring in land_rings for lon, lat in ring]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    k = WIDTH / (maxx - minx)

    def proj(lon, lat):
        x, y = equal_earth(lon, lat, central)
        return (x - minx) * k, (y - miny) * k

    def path(rs, close=True):
        out = []
        for ring in rs:
            xy = [proj(lon, lat) for lon, lat in ring]
            out.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in xy) + ("Z" if close else ""))
        return "".join(out)

    grid = []
    lat = lat0 + step / 2
    while lat < lat1:
        lon = lon0 + step / 2
        while lon < lon1:
            if any(inside_ring(lon, lat, r) for r in land_rings) and not any(inside_ring(lon, lat, r) for r in lake_rings):
                x, y = proj(lon, lat)
                grid.append([round(lat, 2), round(lon, 2), round(x, 1), round(y, 1)])
            lon += step
        lat += step
    mid_lon, mid_lat = (lon0 + lon1) / 2, (lat0 + lat1) / 2
    spacing = math.dist(proj(mid_lon, mid_lat), proj(mid_lon + step, mid_lat))
    return {
        "name": name, "box": [lon0, lon1, lat0, lat1],
        "w": WIDTH, "h": round((maxy - miny) * k, 1),
        "land": path(land_rings), "lakes": path(lake_rings), "borders": path(border_lines, close=False),
        "central": central, "k": k, "minx": minx, "miny": miny,
        "step": step, "spacing": round(spacing, 1), "points": grid,
    }


def main(src_dir, repo, *keys):
    src_dir, repo = Path(src_dir), Path(repo)
    read = lambda f: json.loads((src_dir / f).read_text(encoding="utf-8"))
    src = {"land": read("ne_110m_land.geojson"), "lakes": read("ne_110m_lakes.geojson"),
           "borders": read("ne_110m_admin_0_boundary_lines_land.geojson")}
    out = repo / "backend/app/maps"
    out.mkdir(parents=True, exist_ok=True)
    for key in keys or REGIONS:
        m = build(key, src)
        (out / f"{key}.json").write_text(json.dumps(m, separators=(",", ":")), encoding="utf-8")
        print(f"{key}: {m['w']:.0f}x{m['h']:.0f}, {len(m['points'])} points at {m['step']} deg "
              f"({len(m['points']) * 12} BirdNET-Go calls to build)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
