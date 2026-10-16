"""
Test of versions C and D on a REAL elevation map  (EUDIS Hackathon 2026)

Map: Bråviken bay near Norrköping (real heights from space radar, get_real_map.py):
hills of Kolmården, the flat bay and the flat Norrköping plain.
The magnetic map is SIMULATED (no detailed free magnetic map exists).

Each mission (random place on the map, random directions, random sensor errors):
  a jammer sits on the target and kills GPS within ZONE_R. A drone starts just
  outside, flies in to the target, circles it twice, and flies back out.
  Three edge drones hover just outside the zone with GPS.

Versions:
  IMU only            - no help inside the zone
  C                   - terrain matching (laser + real height map) + edge-drone radio ranging
  D                   - C + MagNav (magnetometer + magnetic map)
Conditions:
  normal              - everything works
  radio jammed        - the jammer also blocks the drones' radio: no edge-drone ranging
  one edge drone lost - one of the three edge drones disappears 2 minutes in

Run: python real_map_test.py   (saves real_map_test.png, ~5 min)
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- SETTINGS ----------------
RUNS = 25
ZONE_R = 4000.0           # m, GPS dead within this distance of the jammer
START_OUT = 1000.0        # m, start this far outside the zone
LOITER_R, LOITER_LAPS = 300.0, 2
SPEED = 20.0              # m/s
DT = 0.2                  # s
IMU_BIAS, IMU_NOISE = 0.02, 0.05
GPS_NOISE = 2.0
RANGE_NOISE, OUTLIER_P = 3.0, 0.03
LASER_NOISE, WAVES = 1.0, 0.3
MAG_NOISE, MAG_DRIFT = 3.0, 0.05
PROFILE_LEN = 60          # 1 Hz samples = 1.2 km of ground
FIX_EVERY = 15.0
SEARCH_MIN, SEARCH_MAX = 150.0, 1500.0
MIN_RELIEF = {"terrain": 3.0, "magnetic": 15.0}
UNIQUE = {"terrain": 1.3, "magnetic": 1.15}
FIX_SIGMA = 20.0
SUCCESS_M = 50.0          # a mission counts as success if the drone never lost track by more than this
SEED = 11
# -------------------------------------------

_m = np.load("real_map.npz")
ELEV = np.maximum(_m["elev"].astype(float), 0.0)       # water surface is at 0
WATER = ELEV <= 3.0
GRID = float(_m["grid"])
H, W = ELEV.shape
EXT_E, EXT_N = W * GRID, H * GRID

# Simulated magnetic anomaly map on a 100 m grid over the same area
_rng = np.random.default_rng(42)
MG = 100.0
_gx, _gy = np.arange(0, EXT_E, MG), np.arange(0, EXT_N, MG)
_GX, _GY = np.meshgrid(_gx, _gy)
MAG = np.zeros(_GX.shape)
for n, (wmin, wmax), amp in [(800, (400, 2500), 200), (4800, (150, 500), 50)]:
    cx, cy = _rng.uniform(0, EXT_E, n), _rng.uniform(0, EXT_N, n)
    w, a = _rng.uniform(wmin, wmax, n), _rng.uniform(-amp, amp, n)
    for x, y, ww, aa in zip(cx, cy, w, a):
        sl = (slice(max(0, int((y - 4 * ww) / MG)), int((y + 4 * ww) / MG) + 1),
              slice(max(0, int((x - 4 * ww) / MG)), int((x + 4 * ww) / MG) + 1))
        MAG[sl] += aa * np.exp(-((_GX[sl] - x) ** 2 + (_GY[sl] - y) ** 2) / (2 * ww * ww))


def lookup(M, cell, x, y):
    fx = np.asarray(x, float) / cell
    fy = np.asarray(y, float) / cell
    ix = np.clip(fx.astype(int), 0, M.shape[1] - 2)
    iy = np.clip(fy.astype(int), 0, M.shape[0] - 2)
    ax, ay = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
    top = M[iy, ix] * (1 - ax) + M[iy, ix + 1] * ax
    bot = M[iy + 1, ix] * (1 - ax) + M[iy + 1, ix + 1] * ax
    return top * (1 - ay) + bot * ay


MAPS = {"terrain": (ELEV, GRID), "magnetic": (MAG, MG)}


def match(kind, pts, meas, search):
    """Slide the measured profile over the map; best shift, or None if flat or ambiguous."""
    m = meas - meas.mean()
    if m.std() < MIN_RELIEF[kind]:
        return None
    M, cell = MAPS[kind]

    def scores(off):
        c = lookup(M, cell, pts[None, :, 0] + off[:, None, 0], pts[None, :, 1] + off[:, None, 1])
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
    if s[far].min() < UNIQUE[kind] * s.min():
        return None
    while step > 2.0:
        step = max(2.0, step / 4)
        fine = grid(best, 4 * step, step)
        best = fine[scores(fine).argmin()]
    return best


def make_mission(rng):
    while True:
        jam = np.array([rng.uniform(ZONE_R + 1500, EXT_E - ZONE_R - 1500), rng.uniform(ZONE_R + 1500, EXT_N - ZONE_R - 1500)])
        a = rng.uniform(0, 2 * np.pi)
        start = jam + (ZONE_R + START_OUT) * np.array([np.cos(a), np.sin(a)])
        if 500 < start[0] < EXT_E - 500 and 500 < start[1] < EXT_N - 500:
            break
    target = jam + rng.uniform(0, 400) * np.array([np.cos(b := rng.uniform(0, 2 * np.pi)), np.sin(b)])
    rot = rng.uniform(0, 2 * np.pi)
    anchors = jam + (ZONE_R + 500) * np.stack([np.cos(rot + np.arange(3) * 2 * np.pi / 3),
                                                np.sin(rot + np.arange(3) * 2 * np.pi / 3)], 1)
    th = np.arctan2(*(target - start)[::-1]) + np.pi
    ang = th + np.linspace(0, 2 * np.pi * LOITER_LAPS, 24 * LOITER_LAPS + 1)
    circle = target + LOITER_R * np.stack([np.cos(ang), np.sin(ang)], 1)
    wps = np.vstack([target, circle, target, start])
    return dict(jam=jam, start=start, target=target, anchors=anchors, wps=wps, n_loiter=len(circle))


def fly(mission, version, condition, seed):
    rng = np.random.default_rng(seed)
    use_terrain = version in ("C", "D")
    use_mag = version == "D"
    use_range = version in ("C", "D") and condition != "radio jammed"
    sources = (["terrain"] if use_terrain else []) + (["magnetic"] if use_mag else [])
    b = IMU_BIAS * np.array([np.cos(a := rng.uniform(0, 2 * np.pi)), np.sin(a)])
    true, est = mission["start"].copy(), mission["start"].copy()
    vel_err, vel_corr, acc_corr = np.zeros(2), np.zeros(2), np.zeros(2)
    I2, Z2 = np.eye(2), np.zeros((2, 2))
    F = np.block([[I2, DT * I2, Z2], [Z2, I2, DT * I2], [Z2, Z2, I2]])
    Q = np.zeros((6, 6)); Q[2:4, 2:4] = I2 * IMU_NOISE**2 * DT; Q[4:6, 4:6] = I2 * (IMU_BIAS * 0.01) ** 2 * DT
    P = np.zeros((6, 6)); P[4:6, 4:6] = I2 * IMU_BIAS**2
    anchors = list(range(3))
    prof = {k: ([], []) for k in sources}
    mag_drift, t, i = 0.0, 0.0, 0
    next_sample, next_fix, entered = 1.0, FIX_EVERY, None
    errs, inside_flags, phase = [], [], []
    track = []
    fixes = {"terrain": 0, "magnetic": 0, "range": 0}

    def update(d, Hm, R, gate):
        nonlocal est, vel_corr, acc_corr, P
        S = Hm @ P @ Hm.T + R
        if d @ np.linalg.solve(S, d) > gate:
            return False
        K = P @ Hm.T @ np.linalg.inv(S)
        dx = K @ d
        est = est - dx[:2]; vel_corr = vel_corr + dx[2:4]; acc_corr = acc_corr + dx[4:6]
        P = (np.eye(6) - K @ Hm) @ P
        for k in sources:
            prof[k] = ([p - dx[:2] for p in prof[k][0]], prof[k][1])
        return True

    wps = mission["wps"]
    while i < len(wps) and t < 2500:
        d = wps[i] - est
        if np.linalg.norm(d) < 12:
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
        inside = np.linalg.norm(true - mission["jam"]) < ZONE_R
        if inside and entered is None:
            entered = t
        if t >= next_sample:
            next_sample += 1.0
            if not inside:
                update(est - (true + rng.normal(0, GPS_NOISE, 2)), np.hstack([I2, Z2, Z2]), I2 * GPS_NOISE**2, 13.8)
            elif use_range:
                if condition == "one edge drone lost" and len(anchors) == 3 and t - entered > 120:
                    anchors.pop(0)
                for k in anchors:
                    a_pos = mission["anchors"][k]
                    a_rep = a_pos + rng.normal(0, GPS_NOISE, 2)
                    z = np.linalg.norm(true - a_pos) + rng.normal(0, RANGE_NOISE)
                    if rng.random() < OUTLIER_P:
                        z += rng.uniform(30, 120)
                    u = (est - a_rep) / np.linalg.norm(est - a_rep)
                    if update(np.array([np.linalg.norm(est - a_rep) - z]), np.hstack([u, np.zeros(4)])[None, :],
                              np.array([[RANGE_NOISE**2 + GPS_NOISE**2]]), 10.8):
                        fixes["range"] += 1
            water = lookup(WATER.astype(float), GRID, *true) > 0.5
            reading = {"terrain": lookup(ELEV, GRID, *true) + rng.normal(0, LASER_NOISE) + (rng.normal(0, WAVES) if water else 0),
                       "magnetic": lookup(MAG, MG, *true) + rng.normal(0, MAG_NOISE) + mag_drift}
            for k in sources:
                prof[k][0].append(est.copy()); prof[k][1].append(reading[k])
                del prof[k][0][:-PROFILE_LEN], prof[k][1][:-PROFILE_LEN]
        if inside and t >= next_fix:
            next_fix = t + FIX_EVERY
            for k in sources:
                if len(prof[k][1]) < PROFILE_LEN:
                    continue
                search = np.clip(3 * np.sqrt(np.linalg.eigvalsh(P[:2, :2]).max()) + 50, SEARCH_MIN, SEARCH_MAX)
                shift = match(k, np.array(prof[k][0]), np.array(prof[k][1]), search)
                if shift is not None and update(-shift, np.hstack([I2, Z2, Z2]), I2 * FIX_SIGMA**2, 13.8):
                    fixes[k] += 1
        errs.append(np.linalg.norm(est - true)); inside_flags.append(inside); phase.append(i)
        track.append(true.copy())
    errs, inside_flags, phase = np.array(errs), np.array(inside_flags), np.array(phase)
    loiter = (phase >= 1) & (phase <= mission["n_loiter"])
    return {"max_inside": errs[inside_flags].max(), "observe": errs[loiter].mean(),
            "t": np.arange(len(errs)) * DT, "err": errs, "inside": inside_flags, "track": np.array(track), "fixes": fixes}


VERSIONS = [("IMU only", "IMU", ["normal"]), ("C: terrain + edge drones", "C", None), ("D: C + MagNav", "D", None)]
CONDITIONS = ["normal", "radio jammed", "one edge drone lost"]


def main():
    rng = np.random.default_rng(SEED)
    missions = [make_mission(rng) for _ in range(RUNS)]
    water_share = np.mean([np.mean(lookup(WATER.astype(float), GRID, *np.linspace(m["start"], m["target"], 50).T) > 0.5)
                           for m in missions])
    print(f"Real map {EXT_E / 1000:.1f} x {EXT_N / 1000:.1f} km (Bråviken). {RUNS} random missions, "
          f"{water_share * 100:.0f} % of the way in is over water on average.\n")
    print(f"{'Version':26s} {'Condition':22s} {'success (<50 m)':>16s} {'max error inside: median / worst':>34s} "
          f"{'error while observing':>22s}  fixes (terrain / mag / radio)")
    results, examples = {}, {}
    for name, v, conds in VERSIONS:
        for cond in conds or CONDITIONS:
            rs = [fly(m, v, cond, SEED * 1000 + k) for k, m in enumerate(missions)]
            mx = np.array([r["max_inside"] for r in rs]); ob = np.array([r["observe"] for r in rs])
            ok = (mx < SUCCESS_M).sum()
            fx = [np.mean([r["fixes"][k] for r in rs]) for k in ("terrain", "magnetic", "range")]
            results[(name, cond)] = (mx, ob, ok)
            examples[(name, cond)] = rs[0]
            print(f"{name:26s} {cond:22s} {ok:7d} / {RUNS:<6d} {np.median(mx):14.0f} m / {mx.max():6.0f} m "
                  f"{np.median(ob):18.0f} m   {fx[0]:5.1f} / {fx[1]:5.1f} / {fx[2]:6.0f}")

    # ---------------- PLOT ----------------
    fig = plt.figure(figsize=(20, 8.5))
    ax = fig.add_axes([0.02, 0.08, 0.40, 0.82])
    ax2 = fig.add_axes([0.47, 0.12, 0.51, 0.76])
    shown = np.where(WATER, np.nan, ELEV)
    ax.imshow(shown, origin="lower", extent=(0, EXT_E, 0, EXT_N), cmap="terrain", vmin=-20, vmax=ELEV.max(), alpha=0.85)
    ax.imshow(np.where(WATER, 1.0, np.nan), origin="lower", extent=(0, EXT_E, 0, EXT_N), cmap="Blues", vmin=0, vmax=1.6)
    th = np.linspace(0, 2 * np.pi, 100)
    for k, m in enumerate(missions):
        ax.plot(m["jam"][0] + ZONE_R * np.cos(th), m["jam"][1] + ZONE_R * np.sin(th), color="#cf222e",
                lw=1.8 if k == 0 else 0.4, alpha=1 if k == 0 else 0.35)
        ax.plot(*np.array([m["start"], m["target"]]).T, color="black", lw=0.6, alpha=0.4)
    m0 = missions[0]
    ax.plot(*examples[("D: C + MagNav", "radio jammed")]["track"].T, color="#1a7f37", lw=2, label="Mission 1, version D, radio jammed")
    ax.scatter(*m0["anchors"].T, marker="^", s=120, color="#1a7f37", edgecolor="black", zorder=5, label="Edge drones (mission 1)")
    ax.scatter(*m0["target"], marker="*", s=300, color="gold", edgecolor="black", zorder=6, label="Target (mission 1)")
    ax.plot([], [], color="#cf222e", lw=1.8, label="GPS-dead zones (25 random missions)")
    ax.set_xlim(0, EXT_E); ax.set_ylim(0, EXT_N); ax.set_aspect("equal")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    ax.set_title("Real heights: Bråviken bay, Kolmården hills (north), plain (south)", fontsize=12)

    labels, data, colors = [], [], []
    palette = {"IMU only": "#e8710a", "C: terrain + edge drones": "#2a6fdb", "D: C + MagNav": "#1a7f37"}
    for (name, cond), (mx, ob, ok) in results.items():
        labels.append(f"{name.split(':')[0]}\n{cond}\n{ok}/{RUNS} ok")
        data.append(mx); colors.append(palette[name])
    bp = ax2.boxplot(data, patch_artist=True, widths=0.6, showfliers=True)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c); patch.set_alpha(0.55)
    ax2.set_xticks(range(1, len(labels) + 1), labels, fontsize=9)
    ax2.axhline(SUCCESS_M, color="#cf222e", ls="--", lw=1, label=f"{SUCCESS_M:.0f} m: 'knows where it is'")
    ax2.set_yscale("log"); ax2.set_ylabel("Max position error inside the zone (m)")
    ax2.grid(alpha=0.3, which="both", axis="y"); ax2.legend(loc="upper right", fontsize=9)
    ax2.set_title(f"{RUNS} random missions on the real map: version C vs D under three conditions", fontsize=12)
    fig.suptitle("Real-map test: terrain matching + edge drones (C) and + MagNav (D) - heights real, magnetic map simulated",
                 fontsize=15, weight="bold")
    plt.savefig("real_map_test.png", dpi=100)
    print("\nSaved real_map_test.png")


if __name__ == "__main__":
    main()
