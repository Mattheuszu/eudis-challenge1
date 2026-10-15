"""Analyse a PX4 SITL .ulg log from a GPS failure-injection test.

Prints console messages (failure injections, failsafes) and plots
EKF estimate vs ground truth, so we can see how PX4 reacts and how
much the position estimate drifts once GPS is gone.

Usage: python analyze_log.py logs/18_23_09.ulg   (saves log_analysis.png)
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
from pyulog import ULog

path = sys.argv[1] if len(sys.argv) > 1 else "logs/18_23_09.ulg"
ulog = ULog(path)
t0 = ulog.start_timestamp


def topic(name):
    data = ulog.get_dataset(name).data
    return (data["timestamp"] - t0) / 1e6, data


# --- Events from the PX4 console --------------------------------------------
KEYWORDS = ("inject", "Cleared", "Failsafe", "Landing", "Takeoff", "Armed", "Disarmed")
events = []
print("Events:")
for msg in ulog.logged_messages:
    if any(k in msg.message for k in KEYWORDS):
        t = (msg.timestamp - t0) / 1e6
        events.append((t, msg.message.strip()))
        print(f"  {t:7.2f} s  {msg.message.strip()}")

injections = [t for t, m in events if "inject failure" in m and "type: ok" not in m]
failsafes = [t for t, m in events if "Failsafe activated" in m]
for t_inj in injections:
    t_fs = next((t for t in failsafes if t >= t_inj), None)
    if t_fs is not None:
        print(f"PX4 reaction time: {t_fs - t_inj:.2f} s (injected at {t_inj:.1f} s)")

# --- Estimate vs ground truth -----------------------------------------------
t_est, est = topic("vehicle_local_position")
t_true, true = topic("vehicle_local_position_groundtruth")
t_gps, gps = topic("sensor_gnss")


def interp_true(key):
    return np.interp(t_est, t_true, true[key])


err_xy = np.hypot(est["x"] - interp_true("x"), est["y"] - interp_true("y"))
alt_est = -est["z"]
alt_true = -interp_true("z")
print(f"Max horizontal estimate error: {err_xy.max():.2f} m at t={t_est[err_xy.argmax()]:.1f} s")

fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True)

axes[0].plot(t_est, alt_true, label="true altitude")
axes[0].plot(t_est, alt_est, "--", label="EKF altitude")
axes[0].set_ylabel("altitude [m]")

axes[1].plot(t_est, err_xy, color="tab:red")
axes[1].set_ylabel("horiz. error [m]")

axes[2].step(t_est, est["xy_valid"], where="post", label="xy_valid")
axes[2].step(t_gps, gps["fix_type"] / 3, where="post", label="GPS fix_type / 3")
axes[2].set_ylabel("flags")

# GPS sample interval: big gaps = signal lost
axes[3].plot(t_gps[1:], np.diff(t_gps), ".")
axes[3].set_ylabel("GPS dt [s]")
axes[3].set_xlabel("time since log start [s]")

for ax in axes:
    for t, m in events:
        if "inject failure" in m:
            ax.axvline(t, color="k", ls=":", lw=1)
        elif "Failsafe activated" in m:
            ax.axvline(t, color="tab:orange", ls="--", lw=1)
    ax.grid(alpha=0.3)
axes[0].legend(loc="upper right")
axes[2].legend(loc="lower left")
axes[0].set_title("PX4 GPS failure test (black: injection, orange: failsafe)")

plt.tight_layout()
plt.savefig("log_analysis.png", dpi=120)
print("Saved log_analysis.png")
