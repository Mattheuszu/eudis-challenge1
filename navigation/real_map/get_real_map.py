"""
Download a real elevation map and turn it into a metre grid for the tests.

Source: AWS Open Data "Terrain Tiles" (elevation-tiles-prod, Terrarium format).
The heights come from space-borne radar mapping (NASA SRTM, about 30 m) and
other public elevation models. Free, no account.

Area: Bråviken bay near Norrköping - the hills of Kolmården on the north
shore, farmland in the south and open water in between. A good real test:
hills, flat fields and sea in one place.

Run: python get_real_map.py   (saves real_map.npz and real_map.png)
"""
import io
import math
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ZOOM = 12
LAT_MIN, LAT_MAX = 58.50, 58.72
LON_MIN, LON_MAX = 16.10, 16.55
GRID = 20.0                                     # m, output grid
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_DIR = "tiles"


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (np.asarray(lon) + 180) / 360 * n
    y = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n
    return x, y


def get_tile(x, y):
    path = os.path.join(TILE_DIR, f"{ZOOM}_{x}_{y}.png")
    if not os.path.exists(path):
        with urllib.request.urlopen(URL.format(z=ZOOM, x=x, y=y), timeout=30) as r:
            data = r.read()
        if not data.startswith(b"\x89PNG"):
            raise ValueError(f"tile {x},{y} is not a PNG")
        with open(path, "wb") as f:
            f.write(data)
    rgb = plt.imread(path)[:, :, :3] * 255.0
    return rgb[:, :, 0] * 256 + rgb[:, :, 1] + rgb[:, :, 2] / 256 - 32768   # Terrarium decoding


def main():
    os.makedirs(TILE_DIR, exist_ok=True)
    x0, y1 = tile_xy(LAT_MIN, LON_MIN, ZOOM)
    x1, y0 = tile_xy(LAT_MAX, LON_MAX, ZOOM)
    xs, ys = range(int(x0), int(x1) + 1), range(int(y0), int(y1) + 1)
    print(f"Downloading {len(xs) * len(ys)} tiles ...")
    rows = []
    for y in ys:
        rows.append(np.hstack([get_tile(x, y) for x in xs]))
    mosaic = np.vstack(rows)                                         # 256 px per tile
    total = sum(os.path.getsize(os.path.join(TILE_DIR, f)) for f in os.listdir(TILE_DIR))
    print(f"Mosaic {mosaic.shape}, {total / 1e6:.1f} MB of tiles")

    # Resample to a local metre grid (east, north) with origin at the south-west corner
    lat0 = math.radians(LAT_MIN)
    width_m = math.radians(LON_MAX - LON_MIN) * 6378137 * math.cos(math.radians((LAT_MIN + LAT_MAX) / 2))
    height_m = math.radians(LAT_MAX - LAT_MIN) * 6378137
    ge = np.arange(0, width_m, GRID)
    gn = np.arange(0, height_m, GRID)
    E, N = np.meshgrid(ge, gn)
    lon = LON_MIN + np.degrees(E / (6378137 * math.cos(math.radians((LAT_MIN + LAT_MAX) / 2))))
    lat = LAT_MIN + np.degrees(N / 6378137)
    tx, ty = tile_xy(lat, lon, ZOOM)
    px = (tx - xs[0]) * 256 - 0.5
    py = (ty - ys[0]) * 256 - 0.5
    ix = np.clip(px.astype(int), 0, mosaic.shape[1] - 2)
    iy = np.clip(py.astype(int), 0, mosaic.shape[0] - 2)
    ax, ay = np.clip(px - ix, 0, 1), np.clip(py - iy, 0, 1)
    top = mosaic[iy, ix] * (1 - ax) + mosaic[iy, ix + 1] * ax
    bot = mosaic[iy + 1, ix] * (1 - ax) + mosaic[iy + 1, ix + 1] * ax
    elev = top * (1 - ay) + bot * ay
    water = elev <= 0.5
    np.savez_compressed("real_map.npz", elev=elev.astype(np.float32), water=water, grid=GRID,
                        lat=[LAT_MIN, LAT_MAX], lon=[LON_MIN, LON_MAX])
    print(f"Grid {elev.shape} at {GRID:.0f} m: {width_m / 1000:.1f} x {height_m / 1000:.1f} km, "
          f"height {elev.min():.0f} to {elev.max():.0f} m, water {water.mean() * 100:.0f} %")

    fig, ax = plt.subplots(figsize=(11, 10))
    shown = np.where(water, np.nan, elev)
    im = ax.imshow(shown, origin="lower", extent=(0, width_m, 0, height_m), cmap="terrain", vmin=-20, vmax=elev.max())
    ax.imshow(np.where(water, 1.0, np.nan), origin="lower", extent=(0, width_m, 0, height_m), cmap="Blues", vmin=0, vmax=1.5)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Height (m)")
    ax.set_title("Real elevation: Bråviken bay, Kolmården (north) and farmland (south)")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    plt.savefig("real_map.png", dpi=90)
    print("Saved real_map.npz and real_map.png")


if __name__ == "__main__":
    main()
