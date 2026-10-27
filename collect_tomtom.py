"""
Collects live traffic speeds for roads in Amman from the TomTom Traffic Flow API
and appends them to a monthly CSV file in the data/ folder.

Each run takes ONE snapshot of every point in points.csv.
Run it every 15 minutes (GitHub Actions does this for you, see collect.yml).

Budget: TomTom's free plan = 2,500 requests/day.
  points x runs per day must stay under 2,500
  20 points x 96 runs (every 15 min) = 1,920  -> OK
"""

import csv
import datetime
import os
import sys
import time
from zoneinfo import ZoneInfo

import requests

KEY = os.environ.get("TOMTOM_KEY")
POINTS_FILE = "points.csv"
OUT_DIR = "data"
# Zoom 22 = full street detail. Lower zooms only include major highways,
# so city-street points get "400 Bad Request" (no road found near the point).
URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/22/json"
MAX_POINTS = 25  # 25 x 96 = 2,400 requests/day, just under the free limit

FIELDS = [
    "timestamp", "weekday", "hour", "minute", "name", "lat", "lon",
    "road_class", "current_speed_kmh", "free_flow_speed_kmh",
    "current_travel_time_s", "free_flow_travel_time_s",
    "congestion_ratio", "confidence", "road_closure",
]


def load_points():
    points = []
    with open(POINTS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name or name.startswith("#"):
                continue
            points.append({
                "name": name,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            })
    if not points:
        sys.exit("points.csv has no points. Add your road points first.")
    if len(points) > MAX_POINTS:
        sys.exit(f"Too many points ({len(points)}). Max is {MAX_POINTS} "
                 "to stay inside the free daily limit.")
    return points


def fetch(point):
    params = {
        "point": f"{point['lat']},{point['lon']}",
        "unit": "KMPH",
        "key": KEY,
    }
    r = requests.get(URL, params=params, timeout=20)
    if r.status_code != 200:
        # Show TomTom's answer, never the URL (it contains the key)
        raise RuntimeError(f"HTTP {r.status_code} from TomTom: {r.text[:200]}")
    return r.json()["flowSegmentData"]


def main():
    if not KEY:
        sys.exit("TOMTOM_KEY is not set. Put your TomTom API key in it first.")

    points = load_points()
    now = datetime.datetime.now(ZoneInfo("Asia/Amman"))

    rows = []
    for p in points:
        try:
            d = fetch(p)
        except Exception as e:
            print(f"[skip] {p['name']}: {str(e).replace(KEY, '***')}")
            continue

        cur = d.get("currentSpeed")
        free = d.get("freeFlowSpeed")
        ratio = round(1 - cur / free, 3) if cur is not None and free else ""

        rows.append({
            "timestamp": now.isoformat(timespec="minutes"),
            "weekday": now.strftime("%A"),
            "hour": now.hour,
            "minute": now.minute,
            "name": p["name"],
            "lat": p["lat"],
            "lon": p["lon"],
            "road_class": d.get("frc"),
            "current_speed_kmh": cur,
            "free_flow_speed_kmh": free,
            "current_travel_time_s": d.get("currentTravelTime"),
            "free_flow_travel_time_s": d.get("freeFlowTravelTime"),
            "congestion_ratio": ratio,
            "confidence": d.get("confidence"),
            "road_closure": d.get("roadClosure"),
        })
        time.sleep(0.3)  # stay well under TomTom's requests-per-second limit

    if not rows:
        sys.exit("FAILED: no point returned data. Read the [skip] lines above "
                 "for TomTom's error (403 = key problem, 400 = bad points).")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"traffic_{now:%Y-%m}.csv")
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerows(rows)

    print(f"{now:%Y-%m-%d %H:%M} saved {len(rows)}/{len(points)} points -> {out_path}")


if __name__ == "__main__":
    main()
