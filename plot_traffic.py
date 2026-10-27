"""
Turns the collected TomTom data into a chart you can show your adviser.

Usage (from the folder that has the data/ folder):
    pip install pandas matplotlib
    python plot_traffic.py

Output: traffic_chart.png  - one small chart per road point, showing the real
measured speed over time (blue line) against that road's free-flow speed (dashed).
When the blue line drops below the dashed line, that's congestion.
"""

import glob
import math

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

LINE = "#2a78d6"
INK = "#2b2b29"
MUTED = "#6b6a63"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

files = sorted(glob.glob("data/traffic_*.csv"))
if not files:
    raise SystemExit("No data yet. Put the data/ folder next to this script first.")

df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
df["timestamp"] = pd.to_datetime(df["timestamp"].str.slice(0, 16))
df = df.dropna(subset=["current_speed_kmh"]).sort_values("timestamp")

points = list(dict.fromkeys(df["name"]))
cols = 2 if len(points) > 1 else 1
rows = math.ceil(len(points) / cols)

fig, axes = plt.subplots(rows, cols, figsize=(7 * cols, 2.6 * rows),
                         squeeze=False)
fig.patch.set_facecolor(SURFACE)

for ax, name in zip(axes.flat, points):
    d = df[df["name"] == name]
    ax.set_facecolor(SURFACE)
    ax.plot(d["timestamp"], d["current_speed_kmh"], color=LINE, linewidth=2)
    ff = d["free_flow_speed_kmh"].median()
    ax.axhline(ff, color=MUTED, linewidth=1, linestyle="--")
    ax.text(1.0, ff, "free-flow ", color=MUTED, fontsize=8, ha="right",
            va="bottom", transform=ax.get_yaxis_transform())
    ax.set_title(name, loc="left", fontsize=10, color=INK)
    ax.set_ylim(0, max(ff, d["current_speed_kmh"].max()) * 1.15)
    ax.set_ylabel("km/h", fontsize=8, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.set_xlim(df["timestamp"].min(), df["timestamp"].max())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))

for ax in list(axes.flat)[len(points):]:
    ax.set_visible(False)

start, end = df["timestamp"].min(), df["timestamp"].max()
snaps = df["timestamp"].nunique()
fig.suptitle(f"Real traffic speed in Amman (TomTom), {start:%d %b %H:%M} to "
             f"{end:%d %b %H:%M} - {snaps} snapshots, {len(df)} readings",
             x=0.01, ha="left", fontsize=11, color=INK)
fig.tight_layout()
fig.savefig("traffic_chart.png", dpi=150, facecolor=SURFACE)
print(f"Saved traffic_chart.png ({len(points)} points, {snaps} snapshots)")
