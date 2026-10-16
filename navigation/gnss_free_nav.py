"""
GNSS-free navigation simulator  (EUDIS Hackathon 2026)
A drone flies a route WITHOUT GPS, using only its IMU (dead reckoning).
Flight 1: IMU only -> drift grows. Flight 2: IMU + checkpoints -> corrected.
"""

import numpy as np
import matplotlib.pyplot as plt

# ---------------- SETTINGS (play with these) ----------------
SPEED = 12.0             # m/s, how fast the drone flies
DT = 0.1                 # s, time step (10 calculations per second)
IMU_BIAS = 0.02          # m/s^2, the IMU's small constant error (causes drift)
IMU_NOISE = 0.05         # m/s^2, random shake in the IMU readings
CAMERA_RANGE = 25.0      # m, how close the drone must be to "see" a checkpoint
MATCH_ERROR = 0.5        # m, how accurate the camera match is
SEED = 7                 # same number = same random result every run

START = np.array([0.0, 0.0])
CHECKPOINTS = np.array([   # known landmarks with known positions
    [300.0, 200.0],
    [650.0, 150.0],
    [900.0, 450.0],
    [1200.0, 500.0],
])
DESTINATION = np.array([1500.0, 800.0])
ROUTE = np.vstack([CHECKPOINTS, DESTINATION])


def fly(use_checkpoints):
    rng = np.random.default_rng(SEED)
    bias = IMU_BIAS * np.array([0.8, -0.6])

    true_pos = START.copy()     # where the drone REALLY is
    est_pos = START.copy()      # where the drone THINKS it is
    vel_error = np.zeros(2)

    log = {"t": [], "true": [], "est": [], "err": [], "fixes": []}
    target_i, t = 0, 0.0
    used = set()

    while target_i < len(ROUTE) and t < 600:
        target = ROUTE[target_i]

        # 1. Steer toward the next waypoint using the ESTIMATED position
        direction = target - est_pos
        dist = np.linalg.norm(direction)
        if dist < 3.0:
            target_i += 1
            continue
        velocity = SPEED * direction / dist

        # 2. Move the drone for real
        true_pos = true_pos + velocity * DT

        # 3. Dead reckoning: y = kx + m, but the IMU error makes k slightly wrong
        accel_error = bias + rng.normal(0, IMU_NOISE, 2)
        vel_error = vel_error + accel_error * DT
        est_pos = est_pos + (velocity + vel_error) * DT

        # 4. Checkpoint correction: camera recognises a nearby landmark
        if use_checkpoints:
            for i, cp in enumerate(CHECKPOINTS):
                if i not in used and np.linalg.norm(true_pos - cp) < CAMERA_RANGE:
                    offset = true_pos - cp
                    before = np.linalg.norm(est_pos - true_pos)
                    est_pos = cp + offset + rng.normal(0, MATCH_ERROR, 2)
                    vel_error = vel_error * 0.2
                    used.add(i)
                    log["fixes"].append((t, before, i + 1))

        t += DT
        log["t"].append(t)
        log["true"].append(true_pos.copy())
        log["est"].append(est_pos.copy())
        log["err"].append(np.linalg.norm(est_pos - true_pos))

    log["true"] = np.array(log["true"])
    log["est"] = np.array(log["est"])
    log["miss"] = np.linalg.norm(log["true"][-1] - DESTINATION)
    return log


no_cp = fly(use_checkpoints=False)
with_cp = fly(use_checkpoints=True)

print("=== RESULTS ===")
print(f"IMU only:          max error {max(no_cp['err']):6.1f} m | "
      f"missed destination by {no_cp['miss']:6.1f} m")
print(f"IMU + checkpoints: max error {max(with_cp['err']):6.1f} m | "
      f"missed destination by {with_cp['miss']:6.1f} m")
for t, before, n in with_cp["fixes"]:
    print(f"  Checkpoint {n} reached at {t:5.1f} s - was {before:5.1f} m off, corrected")

BLUE, ORANGE, GREY = "#2a6fdb", "#e8710a", "#888888"
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

ax1.plot(*no_cp["true"].T, color=ORANGE, lw=2, label="IMU only (real path)")
ax1.plot(*with_cp["true"].T, color=BLUE, lw=2, label="IMU + checkpoints (real path)")
ax1.plot(*np.vstack([START, ROUTE]).T, "--", color=GREY, lw=1, label="Planned route")
ax1.scatter(*CHECKPOINTS.T, s=140, marker="s", color="black", zorder=5, label="Checkpoints")
for i, cp in enumerate(CHECKPOINTS):
    ax1.annotate(f"CP{i+1}", cp, textcoords="offset points", xytext=(8, 8))
ax1.scatter(*START, s=120, color="green", zorder=5, label="Start")
ax1.scatter(*DESTINATION, s=250, marker="*", color="red", zorder=5, label="Destination")
ax1.set_title("Map: where the drone really flew")
ax1.set_xlabel("East (m)"); ax1.set_ylabel("North (m)")
ax1.axis("equal"); ax1.grid(alpha=0.3); ax1.legend(fontsize=8, loc="upper left")

ax2.plot(no_cp["t"], no_cp["err"], color=ORANGE, lw=2, label="IMU only")
ax2.plot(with_cp["t"], with_cp["err"], color=BLUE, lw=2, label="IMU + checkpoints")
for t, before, n in with_cp["fixes"]:
    ax2.axvline(t, color=BLUE, ls=":", alpha=0.5)
    ax2.annotate(f"CP{n}", (t, before), textcoords="offset points", xytext=(4, 4), color=BLUE)
ax2.set_title("Position error over time")
ax2.set_xlabel("Time without GPS (s)"); ax2.set_ylabel("Error (m)")
ax2.grid(alpha=0.3); ax2.legend()

fig.suptitle(f"No GPS: IMU only misses by {no_cp['miss']:.0f} m, "
             f"with checkpoints by {with_cp['miss']:.0f} m", fontsize=14, weight="bold")
plt.tight_layout()
plt.savefig("result.png", dpi=120)
plt.show()
