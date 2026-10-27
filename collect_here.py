"""
Collects live traffic for your road points in Amman from the HERE Traffic API (v7)
and appends them to a monthly CSV file in the data/ folder.

How it works:
  - ONE request per run asks HERE for every road segment in a box around all
    your points (HERE covers Jordan for traffic flow; TomTom does not).
  - For each point in points.csv, it picks the nearest road segment, preferring
    the one whose traffic flows TOWARD that point's intersection (points are
    grouped by the letter before the first "_", e.g. A_..., B_...).

Budget: HERE's free plan = 5,000 traffic requests/month.
  1 request every 15 minutes = about 2,900/month  -> OK
"""

import csv
import datetime
import math
import os
import sys
from zoneinfo import ZoneInfo

import requests

KEY = os.environ.get("HERE_API_KEY")
POINTS_FILE = "points.csv"
OUT_DIR = "data"
URL = "https://data.traffic.hereapi.com/v7/flow"
MARGIN_DEG = 0.004       # ~400 m of extra space around the points
MAX_MATCH_M = 60         # a point further than this from any segment gets no data
TIE_M = 25               # segments within this extra distance count as "same road"

FIELDS = [
    "timestamp", "weekday", "hour", "minute", "name", "lat", "lon",
    "segment", "match_distance_m", "current_speed_kmh", "free_flow_speed_kmh",
    "jam_factor", "congestion_ratio", "confidence", "traversability",
]


def load_points():
    points = []
    with open(POINTS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name or name.startswith("#"):
                continue
            points.append({"name": name, "lat": float(row["lat"]),
                           "lon": float(row["lon"])})
    if not points:
        sys.exit("points.csv has no points. Add your road points first.")
    return points


def intersection_centers(points):
    groups = {}
    for p in points:
        groups.setdefault(p["name"].split("_")[0], []).append(p)
    return {g: (sum(p["lat"] for p in ps) / len(ps),
                sum(p["lon"] for p in ps) / len(ps), len(ps))
            for g, ps in groups.items()}


def to_xy(lat, lon, lat0):
    """Degrees -> metres on a flat local grid (fine at city scale)."""
    return (lon * 111320 * math.cos(math.radians(lat0)), lat * 110540)


def nearest_on_segment(p, a, b):
    """Distance from p to line a-b, plus the direction of a->b."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(p[0] - cx, p[1] - cy), (dx, dy)


def fetch_segments(points):
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    bbox = (f"bbox:{min(lons) - MARGIN_DEG},{min(lats) - MARGIN_DEG},"
            f"{max(lons) + MARGIN_DEG},{max(lats) + MARGIN_DEG}")
    r = requests.get(URL, params={"in": bbox, "locationReferencing": "shape",
                                  "apiKey": KEY}, timeout=30)
    if r.status_code != 200:
        # Show HERE's answer, never the URL (it contains the key)
        sys.exit(f"FAILED: HTTP {r.status_code} from HERE: {r.text[:300]}")
    return r.json().get("results", [])


def match(point, segments, centers):
    lat0 = point["lat"]
    p = to_xy(point["lat"], point["lon"], lat0)
    cand = []
    for seg in segments:
        best = None
        for link in seg.get("location", {}).get("shape", {}).get("links", []):
            pts = [to_xy(q["lat"], q["lng"], lat0) for q in link.get("points", [])]
            for a, b in zip(pts, pts[1:]):
                d, direction = nearest_on_segment(p, a, b)
                if best is None or d < best[0]:
                    best = (d, direction)
        if best:
            cand.append((best[0], best[1], seg))
    if not cand:
        return None
    cand.sort(key=lambda c: c[0])
    if cand[0][0] > MAX_MATCH_M:
        return None

    # Among segments about as close as the nearest one (the two directions of
    # the same road), prefer the one flowing toward this point's intersection.
    group = point["name"].split("_")[0]
    clat, clon, n = centers[group]
    close = [c for c in cand if c[0] <= cand[0][0] + TIE_M]
    if n > 1 and len(close) > 1:
        cx, cy = to_xy(clat, clon, lat0)
        toward = (cx - p[0], cy - p[1])
        close.sort(key=lambda c: -(c[1][0] * toward[0] + c[1][1] * toward[1])
                   / (math.hypot(*c[1]) * math.hypot(*toward) or 1))
        return close[0]
    return cand[0]


def main():
    if not KEY:
        sys.exit("HERE_API_KEY is not set. Put your HERE API key in it first.")

    points = load_points()
    centers = intersection_centers(points)
    now = datetime.datetime.now(ZoneInfo("Asia/Amman"))
    segments = fetch_segments(points)
    print(f"HERE returned {len(segments)} road segments in the area")

    rows = []
    for pt in points:
        m = match(pt, segments, centers)
        if m is None:
            print(f"[skip] {pt['name']}: no HERE road segment within {MAX_MATCH_M} m")
            continue
        dist, _, seg = m
        flow = seg.get("currentFlow", {})
        cur = flow.get("speed")
        free = flow.get("freeFlow")
        cur_kmh = round(cur * 3.6, 1) if cur is not None else ""
        free_kmh = round(free * 3.6, 1) if free is not None else ""
        ratio = round(1 - cur / free, 3) if cur is not None and free else ""
        rows.append({
            "timestamp": now.isoformat(timespec="minutes"),
            "weekday": now.strftime("%A"),
            "hour": now.hour,
            "minute": now.minute,
            "name": pt["name"],
            "lat": pt["lat"],
            "lon": pt["lon"],
            "segment": seg.get("location", {}).get("description", ""),
            "match_distance_m": round(dist, 1),
            "current_speed_kmh": cur_kmh,
            "free_flow_speed_kmh": free_kmh,
            "jam_factor": flow.get("jamFactor"),
            "congestion_ratio": ratio,
            "confidence": flow.get("confidence"),
            "traversability": flow.get("traversability"),
        })

    if not rows:
        sys.exit("FAILED: no point matched a HERE road segment. Check that the "
                 "points in points.csv are on roads.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"here_traffic_{now:%Y-%m}.csv")
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerows(rows)

    print(f"{now:%Y-%m-%d %H:%M} saved {len(rows)}/{len(points)} points -> {out_path}")


if __name__ == "__main__":
    main()
