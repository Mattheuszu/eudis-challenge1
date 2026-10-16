"""
The swarm becomes its own GPS  (EUDIS Hackathon 2026)

Weak spot of swarm_reroute.py: the swarm reaches the target by going AROUND
the jammed area. But the enemy puts the jammer where it protects something -
often the target IS inside the jammed area.

Idea: drones that wait just OUTSIDE the jammed area still have GPS, so they
know exactly where they are. They measure their radio distance to the drone
that flies INSIDE (two-way radio timing, the same principle as GPS). Three
distances from known points = a position. The edge drones become local
satellites that the enemy is not jamming (GPS jammers target the GPS band,
not the drones' own datalink).

Mission: fly into the jammed area to the target, circle it 3 times (observe),
fly back out. Compared:
  1. IMU only inside the zone
  2. Swarm GPS: 3 edge drones, spread around the zone
  3. One edge drone lost halfway (2 left)
  4. Bad placement: 3 edge drones all on one side

Run: python swarm_gps_demo.py   (saves swarm_gps_result.png, ~20 s)
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- SETTINGS (play with these) ----------------
JAMMER = np.array([0.0, 0.0])
GPS_DEAD_R = 1500.0          # m, GPS is lost inside this radius
TARGET = np.array([400.0, 300.0])   # what the jammer protects
LOITER_R = 200.0             # m, circle around the target to observe it
LOITER_LAPS = 3              # observation time grows with laps (1 lap ~ 1 min)
START = np.array([-5000.0, -500.0])
ANCHOR_R = 2000.0            # m from the jammer: outside the dead zone, so they keep GPS
SPEED = 20.0                 # m/s
DT = 0.1                     # s
IMU_BIAS = 0.02              # m/s^2, same drone-grade IMU as the other sims
IMU_NOISE = 0.05             # m/s^2
GPS_NOISE = 2.0              # m
RANGE_NOISE = 3.0            # m, radio ranging accuracy
OUTLIER_P = 0.03             # share of ranges spoiled by reflections (always too long)
RANGE_EVERY = 1.0            # s
GATE_1D = 10.8               # chi-square(1) 99.9 %: reject reflections
RUNS = 20
SEED = 3
# --------------------------------------------------------------


def anchors_at(angles_deg):
    a = np.radians(angles_deg)
    return JAMMER + ANCHOR_R * np.stack([np.cos(a), np.sin(a)], 1)


SCENARIOS = [
    ("IMU only inside the zone", dict(anchors=None), "#e8710a"),
    ("Swarm GPS: 3 edge drones", dict(anchors=anchors_at([90, 210, 330])), "#1a7f37"),
    ("One edge drone lost halfway", dict(anchors=anchors_at([90, 210, 330]), lose_one=True), "#2a6fdb"),
    ("Bad placement: all on one side", dict(anchors=anchors_at([165, 180, 195])), "#8a3ffc"),
]


def mission_waypoints():
    th = np.arctan2(*(TARGET - START)[::-1]) + np.pi
    ang = th + np.linspace(0, 2 * np.pi * LOITER_LAPS, 24 * LOITER_LAPS + 1)
    circle = TARGET + LOITER_R * np.stack([np.cos(ang), np.sin(ang)], 1)
    return np.vstack([TARGET, circle, TARGET, START])


N_LOITER = 24 * LOITER_LAPS + 1


def fly(anchors=None, lose_one=False, seed=SEED):
    rng = np.random.default_rng(seed)
    b = IMU_BIAS * np.array([np.cos(a := rng.uniform(0, 2 * np.pi)), np.sin(a)])
    true, est = START.copy(), START.copy()
    vel_err, vel_corr, acc_corr = np.zeros(2), np.zeros(2), np.zeros(2)
    I2, Z2 = np.eye(2), np.zeros((2, 2))
    F = np.block([[I2, DT * I2, Z2], [Z2, I2, DT * I2], [Z2, Z2, I2]])
    Q = np.zeros((6, 6)); Q[2:4, 2:4] = I2 * IMU_NOISE**2 * DT; Q[4:6, 4:6] = I2 * (IMU_BIAS * 0.01) ** 2 * DT
    P = np.zeros((6, 6)); P[4:6, 4:6] = I2 * IMU_BIAS**2
    active = None if anchors is None else list(range(len(anchors)))
    wps = mission_waypoints()
    i, t, next_meas = 0, 0.0, RANGE_EVERY
    entered, lost_at = None, None
    log = {"t": [], "true": [], "est": [], "err": [], "inside": [], "rejected": 0, "phase": []}

    def update(dvec, H, R):
        nonlocal est, vel_corr, acc_corr, P
        S = H @ P @ H.T + R
        if dvec @ np.linalg.solve(S, dvec) > (GATE_1D if len(dvec) == 1 else 13.8):
            return False
        K = P @ H.T @ np.linalg.inv(S)
        dx = K @ dvec
        est = est - dx[:2]; vel_corr = vel_corr + dx[2:4]; acc_corr = acc_corr + dx[4:6]
        P = (np.eye(6) - K @ H) @ P
        return True

    while i < len(wps) and t < 1500:
        d = wps[i] - est
        if np.linalg.norm(d) < 10:
            i += 1
            continue
        v = SPEED * d / np.linalg.norm(d)
        true = true + v * DT
        vel_err = vel_err + (b + rng.normal(0, IMU_NOISE, 2)) * DT
        vel_corr = vel_corr + acc_corr * DT
        est = est + (v + vel_err - vel_corr) * DT
        P = F @ P @ F.T + Q
        t += DT
        inside = np.linalg.norm(true - JAMMER) < GPS_DEAD_R
        if inside and entered is None:
            entered = t
        if t >= next_meas:
            next_meas += RANGE_EVERY
            if not inside:
                update(est - (true + rng.normal(0, GPS_NOISE, 2)), np.hstack([I2, Z2, Z2]), I2 * GPS_NOISE**2)
            elif active is not None:
                if lose_one and lost_at is None and t - entered > 60:
                    active.pop(0); lost_at = t
                for k in active:
                    a_rep = anchors[k] + rng.normal(0, GPS_NOISE, 2)          # where the edge drone says it is
                    z = np.linalg.norm(true - anchors[k]) + rng.normal(0, RANGE_NOISE)
                    if rng.random() < OUTLIER_P:
                        z += rng.uniform(30, 120)                                # reflection: path too long
                    u = (est - a_rep) / np.linalg.norm(est - a_rep)
                    pred = np.linalg.norm(est - a_rep)
                    H = np.hstack([u, np.zeros(4)])[None, :]
                    if not update(np.array([pred - z]), H, np.array([[RANGE_NOISE**2 + GPS_NOISE**2]])):
                        log["rejected"] += 1
        log["t"].append(t); log["true"].append(true.copy()); log["est"].append(est.copy())
        log["err"].append(np.linalg.norm(est - true)); log["inside"].append(inside)
        log["phase"].append(i)
    for k in ("t", "true", "est", "err", "inside", "phase"):
        log[k] = np.array(log[k])
    ins = log["inside"]
    loiter = (log["phase"] >= 1) & (log["phase"] <= N_LOITER)
    log["max_inside"] = log["err"][ins].max() if ins.any() else np.nan
    log["observe"] = log["err"][loiter].mean() if loiter.any() else np.nan       # how well we know where we were when observing
    log["target_miss"] = np.min(np.linalg.norm(log["true"] - TARGET, axis=1))
    log["home_miss"] = np.linalg.norm(log["true"][-1] - START)
    log["blind_s"] = ins.sum() * DT
    log["lost_at"] = lost_at
    return log


def main():
    print(f"Target inside the jammed area ({GPS_DEAD_R / 1000:.1f} km radius). {RUNS} random runs each.\n")
    print(f"{'Method':34s} {'error while observing':>22s} {'max error inside':>18s} {'closest to target':>18s} {'back home':>10s}")
    shown = {}
    for name, kw, color in SCENARIOS:
        logs = [fly(seed=SEED + r, **kw) for r in range(RUNS)]
        obs = np.array([l["observe"] for l in logs])
        mx = np.array([l["max_inside"] for l in logs])
        tm = np.array([l["target_miss"] for l in logs])
        hm = np.array([l["home_miss"] for l in logs])
        shown[name] = (logs[int(np.argsort(obs)[len(obs) // 2])], color, kw)
        print(f"{name:34s} {np.median(obs):9.0f} m (worst {obs.max():5.0f}) {np.median(mx):11.0f} m "
              f"{np.median(tm):15.0f} m {np.median(hm):9.0f} m")

    fig = plt.figure(figsize=(19, 8))
    ax = fig.add_axes([0.03, 0.08, 0.45, 0.82])
    ax2 = fig.add_axes([0.55, 0.1, 0.43, 0.78])
    th = np.linspace(0, 2 * np.pi, 200)
    ax.fill(JAMMER[0] + GPS_DEAD_R * np.cos(th), JAMMER[1] + GPS_DEAD_R * np.sin(th), color="#cf222e", alpha=0.12)
    ax.plot(JAMMER[0] + GPS_DEAD_R * np.cos(th), JAMMER[1] + GPS_DEAD_R * np.sin(th), "--", color="#cf222e", lw=1.2,
            label="GPS-dead zone")
    ax.scatter(*JAMMER, marker="X", s=160, color="black", zorder=6, label="Jammer")
    ax.scatter(*TARGET, marker="*", s=380, color="gold", edgecolor="black", zorder=7, label="Target (inside the zone)")
    good = shown["Swarm GPS: 3 edge drones"]
    an = good[2]["anchors"]
    k = int(np.argmin(np.linalg.norm(good[0]["true"] - TARGET, axis=1)))
    for a in an:
        ax.plot([a[0], good[0]["true"][k, 0]], [a[1], good[0]["true"][k, 1]], ":", color="#1a7f37", lw=1.2)
    ax.scatter(an[:, 0], an[:, 1], marker="^", s=200, color="#1a7f37", edgecolor="black", zorder=7,
               label="Edge drones with GPS (local satellites)")
    bad_an = shown["Bad placement: all on one side"][2]["anchors"]
    ax.scatter(bad_an[:, 0], bad_an[:, 1], marker="^", s=120, color="#8a3ffc", edgecolor="black", zorder=6,
               label="Bad placement (all west)")
    for name, (log, color, _) in shown.items():
        if name in ("IMU only inside the zone", "Swarm GPS: 3 edge drones"):
            ax.plot(*log["true"].T, color=color, lw=2.2, label=f"{name}: real path")
    ax.plot([], [], ":", color="#1a7f37", label="Radio distance measurements")
    ax.set_xlim(-5500, 3000); ax.set_ylim(-3000, 3000); ax.set_aspect("equal")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)"); ax.grid(alpha=0.25)
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    ax.set_title(f"Fly into the jammed area, circle the target {LOITER_LAPS}×, fly out (typical run)", fontsize=12)

    for name, (log, color, _) in shown.items():
        ax2.plot(log["t"], log["err"], color=color, lw=2, label=name)
        if log["lost_at"]:
            ax2.axvline(log["lost_at"], color=color, ls=":", lw=1.2)
    ins_t = good[0]["t"][good[0]["inside"]]
    ax2.axvspan(ins_t[0], ins_t[-1], color="#cf222e", alpha=0.08, label="inside the GPS-dead zone")
    ax2.set_yscale("log"); ax2.set_ylim(1, 500)
    ax2.set_xlabel("Time (s)"); ax2.set_ylabel("Position error (m)")
    ax2.grid(alpha=0.3, which="both"); ax2.legend(fontsize=9, loc="upper left")
    ax2.set_title("Position error: edge drones keep the inside drone on track", fontsize=12)
    fig.suptitle("The swarm becomes its own GPS: edge drones with GPS guide the drone inside the jammed area",
                 fontsize=15, weight="bold")
    plt.savefig("swarm_gps_result.png", dpi=105)
    print("\nSaved swarm_gps_result.png")


if __name__ == "__main__":
    main()
