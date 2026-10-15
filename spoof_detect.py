"""
Starter project for EUDIS Challenge 1: GNSS-denied navigation + GPS spoofing detection.

What the script does:
  1. Simulates a drone flight in 2D (ground-truth trajectory).
  2. Simulates sensors: IMU (accelerations with noise and bias) and GPS (position with noise).
  3. From t = 60 s an "attack" starts: a GPS spoofer slowly drags the position away.
  4. A Kalman filter fuses IMU + GPS.
  5. Two detectors check whether GPS is lying:
       - detector 1 catches sudden jumps (and misses the slow attack - that's the lesson!);
       - detector 2 looks for a systematic offset over a time window and catches it.
     After the alarm the drone switches to IMU-only navigation.
  6. Plots: ground truth / naive GPS filter / our protected filter.

Run:   pip install numpy matplotlib
       python spoof_detect.py
Try changing the values in the SETTINGS block and see what happens.
"""
import numpy as np
import matplotlib.pyplot as plt

# ---------------- SETTINGS ----------------
DT = 0.1               # time step, s (10 Hz)
T_END = 180            # flight duration, s
ATTACK_START = 60      # when spoofing starts, s
SPOOF_DRIFT = 0.8      # spoofer drag speed, m/s (slow = stealthy attack)
GPS_NOISE = 2.0        # GPS noise, m
ACC_NOISE = 0.15       # accelerometer noise, m/s²
ACC_BIAS = np.array([0.004, -0.003])  # accelerometer bias, m/s² (mid-grade IMU)
# Try ACC_BIAS = [0.02, -0.015] (cheap IMU): after the alarm the error grows fast,
# because bias-induced error grows like t². That is the core of Challenge 1 -
# what replaces GPS: a camera (visual odometry), terrain maps, quantum sensors.
CHI2_THRESHOLD = 9.21  # chi-square threshold (2 DoF, 99%)
ALARM_WINDOW = 10      # consecutive suspicious measurements = alarm
BIAS_WINDOW = 100      # window (measurements = 10 s) for detecting a systematic offset
BIAS_THRESHOLD = 13.8  # chi-square threshold for the window mean (2 DoF, 99.9%)
SEED = 42
# -------------------------------------------

rng = np.random.default_rng(SEED)
t = np.arange(0, T_END, DT)
n = len(t)

# 1. Ground truth: the drone flies a figure-eight
R = 200.0
w = 2 * np.pi / 120
true_pos = np.stack([R * np.sin(w * t), R * np.sin(w * t) * np.cos(w * t)], axis=1)
true_vel = np.gradient(true_pos, DT, axis=0)
true_acc = np.gradient(true_vel, DT, axis=0)

# 2. Sensors
imu_acc = true_acc + ACC_BIAS + rng.normal(0, ACC_NOISE, (n, 2))
gps = true_pos + rng.normal(0, GPS_NOISE, (n, 2))

# 3. Attack: after ATTACK_START, GPS reports a position that slowly drifts away
attack = t >= ATTACK_START
offset = np.zeros((n, 2))
offset[attack, 0] = SPOOF_DRIFT * (t[attack] - ATTACK_START)
offset[attack, 1] = 0.5 * SPOOF_DRIFT * (t[attack] - ATTACK_START)
gps_spoofed = gps + offset

# 4. Kalman filter. State x = [px, py, vx, vy]
F = np.array([[1, 0, DT, 0], [0, 1, 0, DT], [0, 0, 1, 0], [0, 0, 0, 1]])
B = np.array([[0.5 * DT**2, 0], [0, 0.5 * DT**2], [DT, 0], [0, DT]])
H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
Q = B @ B.T * (ACC_NOISE**2) * 4      # process (model) noise
Rm = np.eye(2) * GPS_NOISE**2          # GPS measurement noise

def run_filter(measurements, detector=None):
    x = np.array([*true_pos[0], *true_vel[0]])
    P = np.eye(4)
    est = np.zeros((n, 2))
    nis_log = np.zeros(n)
    trusted = True
    suspicious = 0
    alarm_time = None
    window = []
    history = []   # saved states, to roll back to a "clean" moment
    for k in range(n):
        # Predict using the IMU
        x = F @ x + B @ imu_acc[k]
        P = F @ P @ F.T + Q
        # Innovation: how far GPS disagrees with the prediction
        y = measurements[k] - H @ x
        S = H @ P @ H.T + Rm
        nis = float(y @ np.linalg.solve(S, y))   # Normalized Innovation Squared
        nis_log[k] = nis
        if detector == 'simple' and trusted:
            # Detector 1: catches sudden jumps (each measurement on its own)
            suspicious = suspicious + 1 if nis > CHI2_THRESHOLD else 0
            if suspicious >= ALARM_WINDOW:
                trusted = False
                alarm_time = t[k]
        if detector == 'bias' and trusted:
            # Detector 2: catches slow drag-off. GPS noise averages to zero,
            # but a spoofer causes a persistent one-sided offset -> the window mean grows.
            window.append(np.linalg.solve(np.linalg.cholesky(S), y))  # "whitened" innovation
            if len(window) > BIAS_WINDOW:
                window.pop(0)
                m = np.mean(window, axis=0)
                if BIAS_WINDOW * float(m @ m) > BIAS_THRESHOLD:
                    trusted = False
                    alarm_time = t[k]
                    # Rollback: during the last BIAS_WINDOW steps GPS may already have "infected" the filter.
                    # Go back to the state before the window and re-propagate with IMU only.
                    j = k - BIAS_WINDOW
                    x = history[j].copy()
                    for i in range(j + 1, k + 1):
                        x = F @ x + B @ imu_acc[i]
                        est[i] = x[:2]
                    est[k] = x[:2]
                    continue
        if trusted:
            K = P @ H.T @ np.linalg.inv(S)
            x = x + K @ y
            P = (np.eye(4) - K @ H) @ P
        est[k] = x[:2]
        history.append(x.copy())
    return est, nis_log, alarm_time

naive_est, nis, _ = run_filter(gps_spoofed)
simple_est, _, alarm_simple = run_filter(gps_spoofed, 'simple')
safe_est, _, alarm = run_filter(gps_spoofed, 'bias')
_, _, false_alarm = run_filter(gps, 'bias')   # sanity check: no alarm expected without an attack

err = lambda e: np.linalg.norm(e - true_pos, axis=1)
print(f"Attack started:        t = {ATTACK_START} s")
fmt = lambda a: f"t = {a:.1f} s" if a else "NOT triggered"
print(f"Detector 1 (jumps):    {fmt(alarm_simple)}")
print(f"Detector 2 (offset):   {fmt(alarm)}")
print(f"False alarm without attack (detector 2): {fmt(false_alarm) if false_alarm else 'none - good'}")
print(f"Final error, unprotected: {err(naive_est)[-1]:7.1f} m")
print(f"Final error, detector 2:  {err(safe_est)[-1]:7.1f} m")

# 6. Plots
fig, ax = plt.subplots(1, 3, figsize=(17, 5))
ax[0].plot(*true_pos.T, 'k', lw=2, label='Ground truth')
ax[0].plot(*gps_spoofed.T, '.', ms=1, c='tab:red', alpha=.4, label='GPS (spoofed)')
ax[0].plot(*naive_est.T, c='tab:orange', label='Filter, unprotected')
ax[0].plot(*safe_est.T, c='tab:blue', label='Filter with detector 2')
ax[0].set_title('Trajectory'); ax[0].axis('equal'); ax[0].legend(fontsize=8)

ax[1].plot(t, err(naive_est), c='tab:orange', label='Unprotected')
ax[1].plot(t, err(safe_est), c='tab:blue', label='With detector 2')
ax[1].axvline(ATTACK_START, c='r', ls='--', label='Attack start')
if alarm: ax[1].axvline(alarm, c='g', ls='--', label='Alarm')
ax[1].set_title('Position error, m'); ax[1].set_xlabel('t, s'); ax[1].legend(fontsize=8)

ax[2].semilogy(t, nis, c='tab:purple', lw=.8)
ax[2].axhline(CHI2_THRESHOLD, c='k', ls='--', label='χ² threshold')
ax[2].axvline(ATTACK_START, c='r', ls='--')
ax[2].set_title('NIS - GPS "suspiciousness"'); ax[2].set_xlabel('t, s'); ax[2].legend(fontsize=8)
plt.tight_layout()
plt.savefig('result.png', dpi=120)
plt.show()
