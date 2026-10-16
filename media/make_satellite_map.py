"""Swarm mission from swarm_reroute.py drawn on a real satellite image (illustrative location).

Satellite: Sentinel-2 cloudless 2016 by EOX IT Services GmbH (CC BY 4.0),
contains modified Copernicus Sentinel data 2016. The location (farmland on
Gotland, Baltic Sea) is only a backdrop - the simulation is not tied to it.

Run from the repo root: python media/make_satellite_map.py
-> media/satellite_mission.png, media/satellite_mission.gif, media/satellite_mission.mp4
"""
import math
import os
import sys
import urllib.request

import matplotlib

matplotlib.use("Agg")
import imageio_ffmpeg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter  # noqa: E402
from PIL import Image, ImageEnhance  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import swarm_reroute as S  # noqa: E402

CENTER = (57.20, 18.30)          # illustrative backdrop: farmland, southern Gotland
ZOOM = 14
CACHE = os.path.join(ROOT, "media", ".tiles")
ATTRIB = ("Satellite: Sentinel-2 cloudless 2016 © EOX IT Services GmbH (CC BY 4.0), contains modified Copernicus "
          "Sentinel data. Illustrative location (Gotland, Baltic Sea); drones, jammer and zones are our simulation.")
plt.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()


def tile(z, x, y):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{z}_{y}_{x}.jpg")
    if not os.path.exists(f):
        url = f"https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg"
        req = urllib.request.Request(url, headers={"User-Agent": "EUDIS-hackathon-student-project"})
        with open(f, "wb") as fh:
            fh.write(urllib.request.urlopen(req, timeout=30).read())
    return Image.open(f).convert("RGB")


def backdrop(width_m, height_m):
    lat, lon = CENTER
    n = 2 ** ZOOM
    cx = (lon + 180) / 360 * n * 256
    cy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 256
    mpp = 156543.03392 * math.cos(math.radians(lat)) / n
    w, h = int(width_m / mpp), int(height_m / mpp)
    x0, y0 = cx - w / 2, cy - h / 2
    img = Image.new("RGB", (w, h))
    for ty in range(int(y0 // 256), int((y0 + h) // 256) + 1):
        for tx in range(int(x0 // 256), int((x0 + w) // 256) + 1):
            img.paste(tile(ZOOM, tx, ty), (int(tx * 256 - x0), int(ty * 256 - y0)))
    img = ImageEnhance.Brightness(img).enhance(0.62)        # darker, so the overlay reads
    return ImageEnhance.Contrast(img).enhance(1.15)


def main():
    E0, E1 = S.AREA_E
    N0, N1 = S.AREA_N
    sat = backdrop(E1 - E0, N1 - N0)
    drones, shared, snaps = S.run("swarm", [])
    th = np.linspace(0, 2 * np.pi, 200)
    steps = max(len(d.hist) for d in drones)

    fig = plt.figure(figsize=(13.2, 8.0), dpi=100)
    ax = fig.add_axes([0, 0.06, 1, 0.94])
    ax.imshow(sat, extent=(E0, E1, N0, N1), origin="upper")
    ax.set_xlim(E0, E1); ax.set_ylim(N0, N1); ax.axis("off")
    ax.fill(S.JAMMER[0] + S.TRUE_RADIUS * np.cos(th), S.JAMMER[1] + S.TRUE_RADIUS * np.sin(th),
            color="#ff3b30", alpha=0.22, lw=0)
    ax.plot(S.JAMMER[0] + S.TRUE_RADIUS * np.cos(th), S.JAMMER[1] + S.TRUE_RADIUS * np.sin(th), "--",
            color="#ff6b5e", lw=1.6)
    ax.scatter(*S.JAMMER, marker="X", s=200, color="#ff3b30", edgecolor="white", lw=1.2, zorder=6)
    ax.text(S.JAMMER[0], S.JAMMER[1] - S.TRUE_RADIUS - 120, "GPS JAMMER", color="#ff8a80", ha="center", va="top",
            fontsize=12, weight="bold")
    ax.scatter(*S.TARGET, marker="*", s=700, color="#ffd60a", edgecolor="black", zorder=7)
    ax.text(S.TARGET[0], S.TARGET[1] + 180, "TARGET", color="#ffd60a", ha="center", fontsize=13, weight="bold")
    ax.text(60, 2000, "BASE", color="white", ha="left", va="center", fontsize=13, weight="bold")
    danger = [None]
    trails, dots, blind = [], [], []
    for d in drones:
        trails.append(ax.plot([], [], color=d.color, lw=3.2, solid_capstyle="round")[0])
        blind.append(ax.plot([], [], color="#ff3b30", lw=3.6, ls=":")[0])
        dots.append(ax.plot([], [], "o", ms=12, color=d.color, mec="white", mew=2, zorder=8)[0])
    names = ["SCOUT-1", "UAV-2", "UAV-3"]
    labels = [ax.text(0, 0, n, color="white", fontsize=11, weight="bold", zorder=9) for n in names]
    status = ax.text(0.015, 0.975, "", transform=ax.transAxes, va="top", color="white", fontsize=14, weight="bold",
                     bbox=dict(boxstyle="round,pad=0.4", fc="#0e1621", ec="#f26b1d", alpha=0.9))
    fig.text(0.01, 0.025, ATTRIB, color="#555555", fontsize=8.5, va="center")
    ax.plot([], [], color="#f26b1d", lw=2.5, label="Danger zone shared by the swarm")
    ax.plot([], [], color="#ff3b30", lw=3, ls=":", label="Flying without GPS")
    ax.legend(loc="lower right", fontsize=11, facecolor="#0e1621", edgecolor="#f26b1d", labelcolor="white",
              framealpha=0.9)

    def frame(k):
        k = min(k, steps - 1)
        for i, (d, tr, bl, dot, lab) in enumerate(zip(drones, trails, blind, dots, labels)):
            h = np.array(d.hist[:k + 1]); ok = np.array(d.hist_gps[:k + 1])
            tr.set_data(h[:, 0], h[:, 1])
            bad = h.copy(); bad[ok] = np.nan
            bl.set_data(bad[:, 0], bad[:, 1])
            dot.set_data([h[-1, 0]], [h[-1, 1]])
            lab.set_position((h[-1, 0] + 110, h[-1, 1] + 60 - 190 * i))   # stacked, readable when drones meet
        m = snaps[min(k, len(snaps) - 1)]
        if danger[0] is not None:
            for c in danger[0].collections if hasattr(danger[0], "collections") else [danger[0]]:
                c.remove()
            danger[0] = None
        if m is not None and m.any():
            danger[0] = ax.contour(S.PGE, S.PGN, m.astype(float), levels=[0.5], colors="#f26b1d", linewidths=2.5)
        jammed = [n for d, n in zip(drones, names) if k < len(d.hist_gps) and not d.hist_gps[k] and k >= d.depart]
        arrived = sum(d.arrived is not None and d.arrived <= k * S.DT for d in drones)
        status.set_text(f"T+{int(k * S.DT) // 60:02d}:{int(k * S.DT) % 60:02d}   " +
                        (f"GPS JAMMED: {', '.join(jammed)}" if jammed else f"reached target {arrived}/3"))
        return trails + blind + dots + labels + [status]

    frame(steps - 1)
    out = os.path.join(ROOT, "media")
    fig.savefig(os.path.join(out, "satellite_mission.png"), dpi=110)
    ks = list(range(0, steps, 5)) + [steps - 1] * 25
    anim = FuncAnimation(fig, frame, frames=ks)
    anim.save(os.path.join(out, "satellite_mission.mp4"), writer=FFMpegWriter(fps=15, bitrate=4000), dpi=100)
    FuncAnimation(fig, frame, frames=list(range(0, steps, 9)) + [steps - 1] * 12).save(
        os.path.join(out, "satellite_mission.gif"), writer=PillowWriter(fps=10), dpi=48)
    print("saved media/satellite_mission.png/.mp4/.gif")


if __name__ == "__main__":
    main()
