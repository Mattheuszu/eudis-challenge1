"""Run our spoofing detector on real PX4 SITL sensor data.

Takes IMU + attitude + GPS from a .ulg log, injects a slow, smooth GPS
spoof (position drags away while the fix stays a good 3D fix - unlike
PX4's `failure gps wrong`), and compares:
  - PX4-style per-sample innovation gate (EKF2_GPS_P_GATE = 5 sigma)
  - our windowed-mean detector (from spoof_detect.py)
After our alarm the filter rolls back and continues IMU-only.

Usage: python log_spoof_detect.py logs/18_23_09.ulg   (saves log_spoof_result.png)
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
from pyulog import ULog

# ---------------- SETTINGS ----------------
T_START, T_END = 20.0, 112.5   # clean GPS segment of the log (GPS off injected at 113 s)
ATTACK_START = 80.0            # s since log start (drone hovering at 2.5 m)
SPOOF_SPEED = 0.5              # m/s, final drag speed of the spoofer
SPOOF_DIR = np.deg2rad(30)     # direction of the drag (from north)
SPOOF_RAMP = 5.0               # s, spoofer accelerates smoothly to avoid a jump
EXTRA_GPS_NOISE = 1.5          # m, added to SITL GPS (SITL noise is ~3 cm, real GPS ~1-2 m)
ACC_PROCESS_NOISE = 0.05       # m/s^2 per IMU step (measured SITL accel error ~0.008)
PX4_GATE = 5.0                 # sigma, PX4 default EKF2_GPS_P_GATE
WINDOW = 20                    # GPS samples in the window (~20 s at 1 Hz logged GPS)
WINDOW_THRESHOLD = 18.4        # chi-square(2) 99.99 % (99.9 % gave ~25 % false alarms per run: test repeats every sample)
IMU_RATE = 50                  # Hz, IMU is averaged down from 250 Hz
SEED = 1
# -------------------------------------------

path = sys.argv[1] if len(sys.argv) > 1 else "logs/18_23_09.ulg"
ulog = ULog(path)
t0 = ulog.start_timestamp


def topic(name):
    data = ulog.get_dataset(name).data
    return (data["timestamp"] - t0) / 1e6, data


# --- IMU in NED frame -------------------------------------------------------
t_imu, imu = topic("sensor_combined")
t_att, att = topic("vehicle_attitude")
f_body = np.stack([imu[f"accelerometer_m_s2[{i}]"] for i in range(3)], axis=1)
q = np.stack([np.interp(t_imu, t_att, att[f"q[{i}]"]) for i in range(4)], axis=1)
q /= np.linalg.norm(q, axis=1, keepdims=True)
w, x, y, z = q.T
# Rotation body (FRD) -> NED from quaternion (Hamilton, w first)
rot = np.stack([
    np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
    np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
    np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
], axis=1)
acc_ned = np.einsum("nij,nj->ni", rot, f_body)[:, :2]  # gravity only affects z

# Average down to IMU_RATE
dt = 1.0 / IMU_RATE
grid = np.arange(T_START, T_END, dt)
idx = np.searchsorted(t_imu, grid)
acc = np.array([acc_ned[a:b].mean(axis=0) for a, b in zip(idx[:-1], idx[1:])])
grid = grid[:-1]

# --- GPS and ground truth in local NE metres ---------------------------------
t_gps, gps = topic("sensor_gnss")
t_true, true = topic("vehicle_local_position_groundtruth")
keep = (t_gps >= T_START) & (t_gps < T_END)
t_gps = t_gps[keep]
lat0 = np.deg2rad(true["ref_lat"][0])
lon0 = np.deg2rad(true["ref_lon"][0])
R_EARTH = 6378137.0
gps_ne = np.stack([
    (np.deg2rad(gps["latitude"][keep]) - lat0) * R_EARTH,
    (np.deg2rad(gps["longitude"][keep]) - lon0) * R_EARTH * np.cos(lat0),
], axis=1)
true_ne = np.stack([np.interp(grid, t_true, true["x"]), np.interp(grid, t_true, true["y"])], axis=1)
true_v0 = [np.interp(T_START, t_true, true["vx"]), np.interp(T_START, t_true, true["vy"])]


def spoof_offset(t, speed):
    """Smooth drag: accelerate over SPOOF_RAMP seconds, then constant speed."""
    s = np.clip(t - ATTACK_START, 0, None)
    a = speed / SPOOF_RAMP
    dist = np.where(s < SPOOF_RAMP, 0.5 * a * s**2, 0.5 * speed * SPOOF_RAMP + speed * (s - SPOOF_RAMP))
    return np.outer(dist, [np.cos(SPOOF_DIR), np.sin(SPOOF_DIR)])


# --- Kalman filter (state: n, e, vn, ve) -------------------------------------
F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]])
B = np.array([[0.5 * dt**2, 0], [0, 0.5 * dt**2], [dt, 0], [0, dt]])
H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
Q = B @ B.T * ACC_PROCESS_NOISE**2


def run_filter(meas, gps_sigma, detector):
    """detector: None (trust everything), 'px4' (per-sample gate) or 'window'."""
    Rm = np.eye(2) * gps_sigma**2
    x = np.array([*true_ne[0], *true_v0])
    P = np.eye(4)
    est = np.zeros((len(grid), 2))
    history, window = [], []
    gps_k = np.searchsorted(grid, t_gps)  # IMU step at which each GPS sample arrives
    g = 0
    trusted, alarm = True, None
    for k in range(len(grid)):
        x = F @ x + B @ acc[k]
        P = F @ P @ F.T + Q
        while g < len(t_gps) and gps_k[g] == k:
            y = meas[g] - H @ x
            S = H @ P @ H.T + Rm
            g += 1
            if not trusted:
                continue
            if detector == "px4":
                # PX4 EKF2 rejects a sample if any axis exceeds GATE sigma.
                # It never "alarms" - it just keeps fusing samples that pass.
                if np.any(y**2 > PX4_GATE**2 * np.diag(S)):
                    alarm = alarm or t_gps[g - 1]
                    continue
            if detector == "window":
                window.append(np.linalg.solve(np.linalg.cholesky(S), y))
                window = window[-WINDOW:]
                m = np.mean(window, axis=0)
                if len(window) == WINDOW and WINDOW * float(m @ m) > WINDOW_THRESHOLD:
                    trusted, alarm = False, t_gps[g - 1]
                    # Roll back to before the window, re-propagate IMU-only
                    j = max(k - int(WINDOW * IMU_RATE * 1.0), 0)
                    x = history[j].copy()
                    for i in range(j + 1, k + 1):
                        x = F @ x + B @ acc[i]
                        est[i] = x[:2]
                    continue
            K = P @ H.T @ np.linalg.inv(S)
            x = x + K @ y
            P = (np.eye(4) - K @ H) @ P
        est[k] = x[:2]
        history.append(x.copy())
    return est, alarm


def scenario(extra_noise, speed, seed=SEED, detector="window"):
    rng = np.random.default_rng(seed)
    noisy = gps_ne + rng.normal(0, extra_noise, gps_ne.shape) if extra_noise else gps_ne
    sigma = max(extra_noise, 0.05)
    meas = noisy + (spoof_offset(t_gps, speed) if speed else 0)
    return run_filter(meas, sigma, detector), meas


def err(est):
    return np.linalg.norm(est - true_ne, axis=1)


fmt = lambda a: f"{a - ATTACK_START:5.1f} s after attack" if a else "NOT detected"
for label, noise in [("SITL GPS (~3 cm noise)", 0.0), (f"SITL GPS + {EXTRA_GPS_NOISE} m noise", EXTRA_GPS_NOISE)]:
    print(f"\n=== {label}, spoof {SPOOF_SPEED} m/s from t={ATTACK_START} s ===")
    (naive, _), _ = scenario(noise, SPOOF_SPEED, detector=None)
    (_, a_px4), _ = scenario(noise, SPOOF_SPEED, detector="px4")
    (ours, a_win), _ = scenario(noise, SPOOF_SPEED, detector="window")
    print(f"PX4-style 5-sigma gate: first rejected sample {fmt(a_px4)}")
    print(f"Our window detector:    {fmt(a_win)}")
    print(f"Final error unprotected: {err(naive)[-1]:6.2f} m | with our detector: {err(ours)[-1]:6.2f} m")
    false = [scenario(noise, 0, seed=s)[0][1] for s in range(50)]
    print(f"False alarms without attack: {sum(a is not None for a in false)}/50 noise seeds")

# Detection delay vs spoof speed (realistic noise)
speeds = [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.5]
delay_win, delay_px4 = [], []
for s in speeds:
    a_w = scenario(EXTRA_GPS_NOISE, s)[0][1]
    a_p = scenario(EXTRA_GPS_NOISE, s, detector="px4")[0][1]
    delay_win.append(a_w - ATTACK_START if a_w else np.nan)
    delay_px4.append(a_p - ATTACK_START if a_p else np.nan)
print("\nSpoof speed -> delay (our / PX4 gate), realistic noise:")
for s, a, b in zip(speeds, delay_win, delay_px4):
    print(f"  {s:4.2f} m/s: {a:5.1f} s / {b:5.1f} s")

# --- Plots (realistic-noise case) --------------------------------------------
(naive, _), meas = scenario(EXTRA_GPS_NOISE, SPOOF_SPEED, detector=None)
(ours, alarm), _ = scenario(EXTRA_GPS_NOISE, SPOOF_SPEED)
fig, ax = plt.subplots(1, 3, figsize=(17, 5))
ax[0].plot(true_ne[:, 1], true_ne[:, 0], "k", lw=2, label="Ground truth")
ax[0].plot(meas[:, 1], meas[:, 0], ".", c="tab:red", label="GPS (spoofed)")
ax[0].plot(naive[:, 1], naive[:, 0], c="tab:orange", label="Filter, unprotected")
ax[0].plot(ours[:, 1], ours[:, 0], c="tab:blue", label="Filter, our detector")
ax[0].set_xlabel("East [m]"); ax[0].set_ylabel("North [m]")
ax[0].set_title("Hover at 2.5 m (top view)"); ax[0].axis("equal"); ax[0].legend(fontsize=8)

ax[1].plot(grid, err(naive), c="tab:orange", label="Unprotected")
ax[1].plot(grid, err(ours), c="tab:blue", label="Our detector")
ax[1].axvline(ATTACK_START, c="r", ls="--", label="Spoof start")
if alarm:
    ax[1].axvline(alarm, c="g", ls="--", label=f"Alarm (+{alarm - ATTACK_START:.0f} s)")
ax[1].set_title("Position error [m]"); ax[1].set_xlabel("t [s]"); ax[1].legend(fontsize=8)

ax[2].plot(speeds, delay_win, "o-", label="Our window detector")
ax[2].plot(speeds, delay_px4, "s--", label="PX4-style 5σ gate")
ax[2].set_xscale("log")
ax[2].set_xlabel("Spoof drag speed [m/s]"); ax[2].set_ylabel("Detection delay [s]")
ax[2].set_title("Slower spoof = harder to detect"); ax[2].legend(fontsize=8)
for a in ax:
    a.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("log_spoof_result.png", dpi=120)
print("Saved log_spoof_result.png")
