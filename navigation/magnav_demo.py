"""
MagNav: navigate by the Earth's magnetic fingerprint  (EUDIS Hackathon 2026)

Outside-the-box idea. Rocks under the ground give every place a slightly
different magnetic field (the "crustal anomaly", tens to hundreds of nT).
Geological surveys have mapped it. A magnetometer on the drone measures it
and the drone matches the pattern to the map - the same trick as terrain
matching, but with magnetism instead of hill shape.

Why it is interesting:
  - it cannot be jammed or spoofed (the drone only listens, nothing to fake)
  - it works at night, in fog and in snow
  - it works over FLAT land and over the SEA, where terrain matching fails
    (no hills = nothing for the laser to recognise)

The flight: 20 km, first half over hilly land, second half over the sea.
Compared: IMU only / terrain matching (laser) / MagNav / both together.

Run: python magnav_demo.py      (saves magnav_result.png, ~1 min)
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- SETTINGS (play with these) ----------------
SPEED = 25.0                 # m/s
DT = 0.1                     # s
IMU_BIAS = 0.02              # m/s^2, normal drone-grade IMU
IMU_NOISE = 0.05             # m/s^2
LASER_NOISE = 1.0            # m
WAVES = 0.3                  # m, sea surface seen by the laser
MAG_NOISE = 3.0              # nT, magnetometer + drone's own magnetic noise after compensation
MAG_DRIFT = 0.05             # nT per sqrt(s), slow drift (daily variation) - removed by matching the SHAPE
PROFILE_LEN = 60             # samples in one profile (1 per second = 1.5 km)
FIX_EVERY = 15.0             # s between matches
SEARCH_MIN, SEARCH_MAX = 150.0, 1500.0
UNIQUE_RATIO = {"terrain": 1.3, "magnetic": 1.15}  # best match must beat any match >60 m away by this
                             # factor; the magnetic field is smoother, so a smaller margin is still clear
MIN_RELIEF = {"terrain": 3.0, "magnetic": 15.0}   # m / nT: flatter than this = no usable pattern
FIX_SIGMA = {"terrain": 20.0, "magnetic": 20.0}   # m, how much we trust one match
GATE = 13.8                  # chi-square(2) 99.9 %: throw away implausible matches
COAST_X = 10000.0            # m, land to the west, sea to the east
RUNS = 10                    # random runs for the statistics
SEED = 7
# --------------------------------------------------------------

START = np.array([0.0, 0.0])
ROUTE = np.array([[5000.0, 2500.0], [10000.0, 1000.0], [15000.0, 3500.0], [20000.0, 2000.0]])
DESTINATION = ROUTE[-1]
X_RANGE, Y_RANGE, GRID = (-2000.0, 24000.0), (-4000.0, 8000.0), 50.0

# ---------------- MAPS (stand-ins for real survey maps) ----------------
_gx = np.arange(*X_RANGE, GRID)
_gy = np.arange(*Y_RANGE, GRID)
_GX, _GY = np.meshgrid(_gx, _gy)


def blob_field(rng, n, wmin, wmax, amin, amax):
    cx = rng.uniform(*X_RANGE, n)
    cy = rng.uniform(*Y_RANGE, n)
    w = rng.uniform(wmin, wmax, n)
    a = rng.uniform(amin, amax, n)
    f = np.zeros(_GX.shape)
    for x, y, ww, aa in zip(cx, cy, w, a):
        f += aa * np.exp(-((_GX - x) ** 2 + (_GY - y) ** 2) / (2 * ww * ww))
    return f


_rng = np.random.default_rng(42)
LAND = 1 / (1 + np.exp((_GX - COAST_X) / 400))                      # 1 on land, 0 at sea
TERRAIN_MAP = LAND * blob_field(_rng, 1900, 120, 500, -30, 50)         # hills, flat sea
MAG_MAP = (blob_field(_rng, 400, 400, 2500, -200, 200)                 # deep geology: everywhere
           + blob_field(_rng, 2400, 120, 500, -50, 50))                # shallow rocks: local detail


def lookup(M, x, y):
    """Bilinear read from a map grid. Works on arrays of any shape."""
    fx = (np.asarray(x, float) - X_RANGE[0]) / GRID
    fy = (np.asarray(y, float) - Y_RANGE[0]) / GRID
    ix = np.clip(fx.astype(int), 0, M.shape[1] - 2)
    iy = np.clip(fy.astype(int), 0, M.shape[0] - 2)
    ax, ay = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
    top = M[iy, ix] * (1 - ax) + M[iy, ix + 1] * ax
    bot = M[iy + 1, ix] * (1 - ax) + M[iy + 1, ix + 1] * ax
    return top * (1 - ay) + bot * ay


MAPS = {"terrain": TERRAIN_MAP, "magnetic": MAG_MAP}


def match(kind, pts, meas, search):
    """Slide the measured profile over the map; return the best shift or None.
    Only the SHAPE is compared (mean removed), so constant offsets don't matter."""
    m = meas - meas.mean()
    if m.std() < MIN_RELIEF[kind]:
        return None                                   # flat: nothing to recognise

    def scores(off):
        c = lookup(MAPS[kind], pts[None, :, 0] + off[:, None, 0], pts[None, :, 1] + off[:, None, 1])
        c -= c.mean(axis=1, keepdims=True)
        return np.sqrt(((c - m) ** 2).mean(axis=1))

    def grid(center, half, step):
        g = np.arange(-half, half + step / 2, step)
        return center + np.stack(np.meshgrid(g, g), -1).reshape(-1, 2)

    step = max(10.0, search / 25)
    off = grid(np.zeros(2), search, step)
    s = scores(off)
    best = off[s.argmin()]
    far = np.linalg.norm(off - best, axis=1) > max(60.0, 2 * step)
    if s[far].min() < UNIQUE_RATIO[kind] * s.min():
        return None                                   # another place fits as well: ambiguous
    while step > 2.0:
        step = max(2.0, step / 4)
        fine = grid(best, 4 * step, step)
        best = fine[scores(fine).argmin()]
    return best


def fly(sources, seed):
    """One flight. sources: which matchers the drone uses ([], ["terrain"], ...)."""
    rng = np.random.default_rng(seed)
    b = IMU_BIAS * np.array([np.cos(a := rng.uniform(0, 2 * np.pi)), np.sin(a)])
    true, est = START.copy(), START.copy()
    vel_err, vel_corr, acc_corr = np.zeros(2), np.zeros(2), np.zeros(2)
    mag_drift = 0.0
    I2, Z2 = np.eye(2), np.zeros((2, 2))
    F = np.block([[I2, DT * I2, Z2], [Z2, I2, DT * I2], [Z2, Z2, I2]])
    Q = np.zeros((6, 6)); Q[2:4, 2:4] = I2 * IMU_NOISE**2 * DT; Q[4:6, 4:6] = I2 * (IMU_BIAS * 0.01) ** 2 * DT
    P = np.zeros((6, 6)); P[4:6, 4:6] = I2 * IMU_BIAS**2
    prof = {k: ([], []) for k in sources}
    next_sample, next_fix = 1.0, FIX_EVERY
    log = {"t": [], "true": [], "err": [], "fixes": [], "rejected": {k: 0 for k in sources}}
    i, t = 0, 0.0
    while i < len(ROUTE) and t < 2000:
        d = ROUTE[i] - est
        if np.linalg.norm(d) < 15:
            i += 1
            continue
        v = SPEED * d / np.linalg.norm(d)
        true = true + v * DT
        vel_err = vel_err + (b + rng.normal(0, IMU_NOISE, 2)) * DT
        vel_corr = vel_corr + acc_corr * DT
        est = est + (v + vel_err - vel_corr) * DT
        P = F @ P @ F.T + Q
        t += DT
        mag_drift += rng.normal(0, MAG_DRIFT * np.sqrt(DT))
        if t >= next_sample:
            next_sample += 1.0
            sea = true[0] > COAST_X
            reading = {
                "terrain": lookup(TERRAIN_MAP, *true) + rng.normal(0, LASER_NOISE) + (rng.normal(0, WAVES) if sea else 0),
                "magnetic": lookup(MAG_MAP, *true) + rng.normal(0, MAG_NOISE) + mag_drift,
            }
            for k in sources:
                prof[k][0].append(est.copy()); prof[k][1].append(reading[k])
                del prof[k][0][:-PROFILE_LEN], prof[k][1][:-PROFILE_LEN]
        if t >= next_fix:
            next_fix += FIX_EVERY
            for k in sources:
                if len(prof[k][1]) < PROFILE_LEN:
                    continue
                search = np.clip(3 * np.sqrt(np.linalg.eigvalsh(P[:2, :2]).max()) + 50, SEARCH_MIN, SEARCH_MAX)
                shift = match(k, np.array(prof[k][0]), np.array(prof[k][1]), search)
                if shift is None:
                    log["rejected"][k] += 1
                    continue
                dd = -shift                                   # estimate minus what the map says
                S = P[:2, :2] + I2 * FIX_SIGMA[k] ** 2
                if dd @ np.linalg.solve(S, dd) > GATE:
                    log["rejected"][k] += 1
                    continue
                K = P[:, :2] @ np.linalg.inv(S)
                dx = K @ dd
                est = est - dx[:2]
                for kk in sources:                            # keep every stored profile consistent
                    prof[kk] = ([p - dx[:2] for p in prof[kk][0]], prof[kk][1])
                vel_corr = vel_corr + dx[2:4]
                acc_corr = acc_corr + dx[4:6]
                P = (np.eye(6) - K @ np.hstack([I2, Z2, Z2])) @ P
                log["fixes"].append((t, k, true[0] > COAST_X))
        log["t"].append(t); log["true"].append(true.copy()); log["err"].append(np.linalg.norm(est - true))
    log["true"] = np.array(log["true"]); log["err"] = np.array(log["err"]); log["t"] = np.array(log["t"])
    log["miss"] = np.linalg.norm(log["true"][-1] - DESTINATION)
    sea = log["true"][:, 0] > COAST_X
    log["max_land"] = log["err"][~sea].max()
    log["max_sea"] = log["err"][sea].max() if sea.any() else np.nan
    return log


SCENARIOS = [
    ("IMU only", [], "#e8710a"),
    ("Terrain matching (laser)", ["terrain"], "#2a6fdb"),
    ("MagNav (magnetometer)", ["magnetic"], "#8a3ffc"),
    ("Both together", ["terrain", "magnetic"], "#1a7f37"),
]


def main():
    print(f"20 km flight: land (hills) until x = {COAST_X / 1000:.0f} km, then sea. {RUNS} random runs each.\n")
    print(f"{'Method':28s} {'missed by (median / worst)':>28s} {'max error over sea':>20s}  fixes land / sea")
    shown = {}
    for name, src, color in SCENARIOS:
        logs = [fly(src, SEED + r) for r in range(RUNS)]
        miss = np.array([l["miss"] for l in logs])
        shown[name] = (logs[int(np.argsort(miss)[len(miss) // 2])], color)   # the typical (median) run
        sea_max = np.array([l["max_sea"] for l in logs])
        land_fix = np.mean([sum(1 for f in l["fixes"] if not f[2]) for l in logs])
        sea_fix = np.mean([sum(1 for f in l["fixes"] if f[2]) for l in logs])
        print(f"{name:28s} {np.median(miss):11.0f} m / {miss.max():6.0f} m {np.median(sea_max):16.0f} m  "
              f"{land_fix:5.1f} / {sea_fix:4.1f}")

    fig = plt.figure(figsize=(19, 7.5))
    ax = fig.add_axes([0.035, 0.09, 0.56, 0.8])
    ax2 = fig.add_axes([0.66, 0.09, 0.32, 0.8])
    lim = 1.05 * np.abs(MAG_MAP).max()
    im = ax.imshow(MAG_MAP, extent=(*X_RANGE, *Y_RANGE), origin="lower", cmap="RdBu_r", vmin=-lim, vmax=lim, alpha=0.75)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Magnetic anomaly (nT)")
    ax.contour(_GX, _GY, TERRAIN_MAP, levels=8, colors="#333333", linewidths=0.5, alpha=0.6)
    ax.axvline(COAST_X, color="black", lw=2)
    ax.text(COAST_X - 300, Y_RANGE[1] - 600, "LAND (hills)", ha="right", fontsize=12, weight="bold")
    ax.text(COAST_X + 300, Y_RANGE[1] - 600, "SEA (flat)", ha="left", fontsize=12, weight="bold")
    ax.plot(*np.vstack([START, ROUTE]).T, "--", color="black", lw=1, label="Planned route")
    for name, (log, color) in shown.items():
        ax.plot(*log["true"].T, color=color, lw=2.2, label=f"{name}: missed by {log['miss']:.0f} m")
    ax.scatter(*START, s=120, color="green", zorder=5)
    ax.scatter(*DESTINATION, s=300, marker="*", color="gold", edgecolor="black", zorder=5)
    ax.set_xlim(*X_RANGE); ax.set_ylim(*Y_RANGE); ax.set_aspect("equal")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    ax.set_title("Map: colours = magnetic fingerprint, grey lines = hills (typical run of each method)", fontsize=12)

    for name, (log, color) in shown.items():
        label = f"{name} (off the chart: lost)" if name == "IMU only" else name
        ax2.plot(log["t"], log["err"], color=color, lw=2, label=label)
    ref = shown["Terrain matching (laser)"][0]
    sea_t = ref["t"][ref["true"][:, 0] > COAST_X]
    if len(sea_t):
        ax2.axvspan(sea_t[0], sea_t[-1], color="#9ec9ff", alpha=0.25, label="over the sea")
    ax2.set_yscale("log"); ax2.set_ylim(1, 3000)
    ax2.set_xlim(0, max(l["t"][-1] for n, (l, _) in shown.items() if n != "IMU only") + 30)
    ax2.set_xlabel("Time without GPS (s)"); ax2.set_ylabel("Position error (m)")
    ax2.grid(alpha=0.3, which="both"); ax2.legend(fontsize=9, loc="upper left")
    ax2.set_title("Position error: terrain matching goes blind over the sea", fontsize=12)
    fig.suptitle("MagNav: the Earth's magnetic field as a map that cannot be jammed - works where hills don't",
                 fontsize=15, weight="bold")
    plt.savefig("magnav_result.png", dpi=105)
    print("\nSaved magnav_result.png")


if __name__ == "__main__":
    main()
