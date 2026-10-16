"""
Long-range GNSS-free navigation simulator  (EUDIS Hackathon 2026)
An ~9 km flight without GPS, on a snowy day.

Problem: IMU drift grows with time squared -> fine at 300 m, kilometres off at 9 km.
         Camera landmarks fix it on a normal day, but snow hides most landmarks.
Solution: terrain matching. A laser altimeter measures the height profile of the
         ground under the drone and matches it against a height map. Snow covers
         objects but not the shape of the hills, so this still works in winter.

Run: python sim_long.py   (saves sim_long_result.png)
"""

import matplotlib

matplotlib.use("Agg")  # just save the picture, no window
import matplotlib.pyplot as plt
import numpy as np

# ---------------- SETTINGS (play with these) ----------------
SPEED = 20.0             # m/s
DT = 0.1                 # s
IMU_BIAS = 0.02          # m/s^2, normal drone-grade (MEMS) IMU
IMU_NOISE = 0.05         # m/s^2
QUANTUM_BIAS = 0.0005    # m/s^2, simulated quantum accelerometer (40x better)
QUANTUM_NOISE = 0.005    # m/s^2
SEED = 7

# Camera landmarks
CAMERA_RANGE = 100.0     # m, landmark must be this close to be seen
SEE_PROB = {"normal": 0.9, "snow": 0.25}   # chance the camera recognises a landmark
MATCH_ERROR = {"normal": 2.0, "snow": 5.0}  # m

# Terrain matching (laser altimeter + height map)
LASER_NOISE = 1.0        # m
SNOW_DEPTH = 0.8         # m, snow layer on top of the ground (+ drifts, see snow())
PROFILE_LEN = 60         # samples in one height profile (1 per second = 1.2 km of ground)
TERRAIN_EVERY = 15.0     # s between terrain matches
SEARCH_MIN, SEARCH_MAX = 150.0, 1000.0   # m, search area grows when the filter is unsure
MIN_RELIEF = 3.0         # m, flatter ground than this is not trusted (lake, field)
UNIQUE_RATIO = 1.3       # best match must beat any match >60 m away by this factor

TERRAIN_SIGMA = 20.0     # m, how much we trust one terrain match
GATE = 13.8              # chi-square(2) 99.9 %: fixes further off than this are thrown away

START = np.array([0.0, 0.0])
WAYPOINTS = np.array([
    [2000.0, 800.0],
    [4000.0, 300.0],
    [6000.0, 1800.0],
    [8000.0, 2500.0],
])
DESTINATION = WAYPOINTS[-1]
ROUTE = WAYPOINTS

# ---------------- TERRAIN (stands in for a real height map) ----------------
trng = np.random.default_rng(42)
N_HILLS = 400
hx = trng.uniform(-1000, 10000, N_HILLS)
hy = trng.uniform(-1500, 4500, N_HILLS)
ha = trng.uniform(-30, 50, N_HILLS)      # hill height (negative = valley)
hw = trng.uniform(120, 500, N_HILLS)     # hill width


def hills(x, y):
    h = np.zeros(np.broadcast(x, y).shape)
    for cx, cy, a, w in zip(hx, hy, ha, hw):
        h += a * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * w * w))
    return h


# Height map as a 10 m grid, like a real national elevation model
GRID = 10.0
MAP_X0, MAP_Y0 = -1500.0, -2000.0
_gx = np.arange(MAP_X0, 10500, GRID)
_gy = np.arange(MAP_Y0, 5000, GRID)
HEIGHT_MAP = hills(_gx[None, :], _gy[:, None])


def terrain(x, y):
    """Ground height [m] at (x, y), read from the height map (bilinear). Any array shape."""
    fx = (np.asarray(x, float) - MAP_X0) / GRID
    fy = (np.asarray(y, float) - MAP_Y0) / GRID
    ix = np.clip(fx.astype(int), 0, HEIGHT_MAP.shape[1] - 2)
    iy = np.clip(fy.astype(int), 0, HEIGHT_MAP.shape[0] - 2)
    ax, ay = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
    top = HEIGHT_MAP[iy, ix] * (1 - ax) + HEIGHT_MAP[iy, ix + 1] * ax
    bot = HEIGHT_MAP[iy + 1, ix] * (1 - ax) + HEIGHT_MAP[iy + 1, ix + 1] * ax
    return top * (1 - ay) + bot * ay


def snow(x, y):
    """Snow depth: a layer plus uneven drifts."""
    return SNOW_DEPTH + 0.4 * np.sin(x / 37.0) * np.cos(y / 53.0)


# Landmarks every ~1 km along the planned route
path = np.vstack([START, ROUTE])
seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
cum = np.concatenate([[0], np.cumsum(seg)])
ROUTE_LENGTH = cum[-1]
marks = np.arange(1000, ROUTE_LENGTH - 200, 1000)
LANDMARKS = np.array([np.interp(marks, cum, path[:, 0]), np.interp(marks, cum, path[:, 1])]).T


def tercom(pts, meas, search):
    """Find the shift of our estimated track that best fits the measured heights,
    looking up to `search` metres away.
    Heights are compared after removing their mean, so a constant offset
    (snow layer, barometer error) does not matter - only the SHAPE does."""
    m = meas - meas.mean()
    if m.std() < MIN_RELIEF:
        return None  # ground too flat to match

    def scores(offsets):
        cand = terrain(pts[None, :, 0] + offsets[:, None, 0], pts[None, :, 1] + offsets[:, None, 1])
        cand -= cand.mean(axis=1, keepdims=True)
        return np.sqrt(((cand - m) ** 2).mean(axis=1))

    def grid(center, half, step):
        g = np.arange(-half, half + step / 2, step)
        return center + np.stack(np.meshgrid(g, g), -1).reshape(-1, 2)

    step = max(10.0, search / 25)
    off = grid(np.zeros(2), search, step)
    s = scores(off)
    best = off[s.argmin()]
    far = np.linalg.norm(off - best, axis=1) > max(60.0, 2 * step)
    if s[far].min() < UNIQUE_RATIO * s.min():
        return None  # another place fits almost as well -> ambiguous, don't trust it
    # Zoom in around the best coarse match until we are at 2 m resolution
    while step > 2.0:
        step = max(2.0, step / 4)
        fine = grid(best, 4 * step, step)
        best = fine[scores(fine).argmin()]
    return best


def fly(use_camera=False, use_terrain=False, weather="normal",
        bias=IMU_BIAS, noise=IMU_NOISE):
    rng = np.random.default_rng(SEED)
    b = bias * np.array([0.8, -0.6])

    true_pos, est_pos = START.copy(), START.copy()
    vel_err = np.zeros(2)                     # real IMU velocity error
    vel_corr = np.zeros(2)                    # velocity error the drone has learned
    acc_corr = np.zeros(2)                    # IMU bias the drone has learned
    baro = 0.0                                # slowly wandering barometer error
    prof_est, prof_h = [], []
    next_sample, next_tercom = 1.0, TERRAIN_EVERY
    tried = set()

    # Kalman filter on the navigation ERROR: [position x2, velocity x2, IMU bias x2].
    # It knows how fast IMU errors grow, so it can tell from a few fixes how big the
    # bias is, and keeps cancelling it between fixes.
    I2, Z2 = np.eye(2), np.zeros((2, 2))
    F = np.block([[I2, DT * I2, Z2], [Z2, I2, DT * I2], [Z2, Z2, I2]])
    Q = np.zeros((6, 6))
    Q[2:4, 2:4] = I2 * noise**2 * DT
    Q[4:6, 4:6] = I2 * (bias * 0.01) ** 2 * DT
    P = np.zeros((6, 6))
    P[4:6, 4:6] = I2 * bias**2               # we only know roughly how big the bias can be

    log = {"t": [], "true": [], "est": [], "err": [], "fixes": [], "rejected": 0, "seen": 0,
           "terrain_fixes": 0, "gated": 0}
    target_i, t = 0, 0.0

    while target_i < len(ROUTE) and t < 1500:
        direction = ROUTE[target_i] - est_pos
        dist = np.linalg.norm(direction)
        if dist < 10.0:
            target_i += 1
            continue
        velocity = SPEED * direction / dist

        true_pos = true_pos + velocity * DT
        vel_err = vel_err + (b + rng.normal(0, noise, 2)) * DT
        vel_corr = vel_corr + acc_corr * DT
        est_pos = est_pos + (velocity + vel_err - vel_corr) * DT
        P = F @ P @ F.T + Q
        t += DT

        fix = None   # (measured position, its sigma, kind)
        if use_camera:
            for i, lm in enumerate(LANDMARKS):
                if i not in tried and np.linalg.norm(true_pos - lm) < CAMERA_RANGE:
                    tried.add(i)
                    if rng.random() < SEE_PROB[weather]:
                        log["seen"] += 1
                        fix = (true_pos + rng.normal(0, MATCH_ERROR[weather], 2), MATCH_ERROR[weather], "camera")

        if use_terrain:
            baro += rng.normal(0, 0.02)
            if t >= next_sample:
                next_sample += 1.0
                h = terrain(*true_pos) + baro + rng.normal(0, LASER_NOISE)
                if weather == "snow":
                    h += snow(*true_pos)
                prof_est.append(est_pos.copy())
                prof_h.append(h)
                prof_est, prof_h = prof_est[-PROFILE_LEN:], prof_h[-PROFILE_LEN:]
            if t >= next_tercom and fix is None:
                next_tercom += TERRAIN_EVERY
                if len(prof_h) == PROFILE_LEN:
                    unsure = 3 * np.sqrt(np.linalg.eigvalsh(P[:2, :2]).max()) + 50
                    search = np.clip(unsure, SEARCH_MIN, SEARCH_MAX)
                    shift = tercom(np.array(prof_est), np.array(prof_h), search)
                    if shift is None:
                        log["rejected"] += 1
                    else:
                        fix = (est_pos + shift, TERRAIN_SIGMA, "terrain")

        if fix is not None:
            meas, sigma, kind = fix
            d = est_pos - meas                     # how far off the fix says we are
            S = P[:2, :2] + I2 * sigma**2
            if d @ np.linalg.solve(S, d) > GATE:
                log["gated"] += 1                  # implausible fix (wrong match) -> ignore
            else:
                K = P[:, :2] @ np.linalg.inv(S)
                dx = K @ d
                log["fixes"].append((t, np.linalg.norm(est_pos - true_pos), kind))
                log["terrain_fixes"] += kind == "terrain"
                est_pos = est_pos - dx[:2]
                prof_est = [p - dx[:2] for p in prof_est]
                vel_corr = vel_corr + dx[2:4]
                acc_corr = acc_corr + dx[4:6]
                P = (np.eye(6) - K @ np.hstack([I2, Z2, Z2])) @ P

        log["t"].append(t)
        log["true"].append(true_pos.copy())
        log["est"].append(est_pos.copy())
        log["err"].append(np.linalg.norm(est_pos - true_pos))

    log["true"] = np.array(log["true"])
    log["err"] = np.array(log["err"])
    log["miss"] = np.linalg.norm(log["true"][-1] - DESTINATION)
    return log


SCENARIOS = [
    ("IMU only", dict(), "#e8710a"),
    ("IMU + camera, normal day", dict(use_camera=True), "#8a63d2"),
    ("IMU + camera, snow", dict(use_camera=True, weather="snow"), "#d6336c"),
    ("IMU + terrain match, snow", dict(use_terrain=True, weather="snow"), "#2a6fdb"),
    ("IMU + terrain + camera, snow", dict(use_terrain=True, use_camera=True, weather="snow"), "#1a7f37"),
    ("Quantum IMU only (bonus)", dict(bias=QUANTUM_BIAS, noise=QUANTUM_NOISE), "#6e7781"),
]

def run_all():
    """Fly every scenario, print the results table, return [(name, log, color)]."""
    print(f"Route length {ROUTE_LENGTH / 1000:.1f} km, {len(LANDMARKS)} landmarks, speed {SPEED:.0f} m/s\n")
    print(f"{'Scenario':32s} {'max error':>10s} {'missed by':>10s}  notes")
    results = []
    for name, kw, color in SCENARIOS:
        r = fly(**kw)
        results.append((name, r, color))
        notes = []
        if kw.get("use_camera"):
            notes.append(f"landmarks seen {r['seen']}/{len(LANDMARKS)}")
        if kw.get("use_terrain"):
            notes.append(f"terrain fixes {r['terrain_fixes']}, ambiguous {r['rejected']}")
        if r["gated"]:
            notes.append(f"thrown away {r['gated']}")
        print(f"{name:32s} {r['err'].max():8.1f} m {r['miss']:8.1f} m  {', '.join(notes)}")
    return results


def main():
    results = run_all()

    # ---------------- PLOT ----------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6.5), gridspec_kw={"width_ratios": [1.4, 1]})

    gx = np.linspace(-500, 9000, 300)
    gy = np.linspace(-1500, 4000, 180)
    GX, GY = np.meshgrid(gx, gy)
    ax1.contourf(GX, GY, terrain(GX, GY), levels=20, cmap="Greys", alpha=0.45)
    ax1.plot(*np.vstack([START, ROUTE]).T, "--", color="black", lw=1, label="Planned route")
    for name, r, color in results:
        if name.startswith("Quantum") or "normal" in name:
            continue
        ax1.plot(*r["true"].T, color=color, lw=2, label=f"{name} (real path)")
    ax1.scatter(*LANDMARKS.T, s=60, marker="s", color="black", zorder=5, label="Camera landmarks")
    ax1.scatter(*START, s=120, color="green", zorder=5, label="Start")
    ax1.scatter(*DESTINATION, s=250, marker="*", color="red", zorder=5, label="Destination")
    ax1.set_title("Map (grey = hills from the height map)")
    ax1.set_xlabel("East (m)"); ax1.set_ylabel("North (m)")
    ax1.set_aspect("equal"); ax1.legend(fontsize=8, loc="lower right")

    for name, r, color in results:
        ax2.plot(r["t"], r["err"], color=color, lw=2, label=f"{name}: missed by {r['miss']:.0f} m")
    ax2.set_yscale("log")
    ax2.set_ylim(0.5, None)
    ax2.set_title("Position error over time (log scale)")
    ax2.set_xlabel("Time without GPS (s)"); ax2.set_ylabel("Error (m)")
    ax2.grid(alpha=0.3, which="both"); ax2.legend(fontsize=8, loc="upper left")

    terr = next(r for n, r, _ in results if n.startswith("IMU + terrain match"))
    imu = results[0][1]
    fig.suptitle(f"{ROUTE_LENGTH / 1000:.1f} km without GPS in snow: IMU only misses by {imu['miss']:.0f} m, "
                 f"terrain matching by {terr['miss']:.0f} m", fontsize=14, weight="bold")
    plt.tight_layout()
    plt.savefig("sim_long_result.png", dpi=120)
    print("\nSaved sim_long_result.png")


if __name__ == "__main__":
    main()
