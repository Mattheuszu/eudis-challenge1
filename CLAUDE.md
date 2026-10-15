# EUDIS Defence Hackathon 2026 — Challenge 1 (GNSS-denied navigation)

Context handoff for Claude Code. The user (Den) prefers Russian in chat; code and comments in English.

## Event
- EUDIS Defence Hackathon, Linköping, Sweden. Venue: Zenit (Linköping Science Park / LiU). 48 h, Thu 15 – Sat 17 Oct 2026.
- **Deadline: upload pitch presentation Sat 17 Oct 12:30.** Pitch = 5 min, Sat 13:30–15:30. Live demos Sat 9:00–12:00 for jury/mentors (Terra lab or outdoors).
- Fri 16 Oct: mentor session 1 at 9:45–12:00, Checkpoint 2 at 13:00, mentor session 2 at 15:30–17:00, dinner at Air Force Museum from 17:00.
- Jury criteria: team, progress made during the hackathon, innovativeness, relevance to the challenge.
- Prizes: 1st €5,000 + EUDIS mentorship, 2nd €3,000, 3rd €2,000.
- Terra lab (LiU): 10×10×5 m indoor flight space with Vicon tracking, 3× Holybro drones (Pixhawk 6C, PX4), XSens MTi-G-700 IMU, Jetson Orin NX, 2× DJI M300 (hardware-in-the-loop only).

## Team
- Den: cyber security student. Owns detection / security logic.
- Friend: computer engineering, beginner. Owns visualisation, graphs, slides.

## Challenge 1 (official text, summarised)
Autonomous systems that navigate without GNSS using onboard sensors and real-time perception. Bonus: quantum sensors (accelerometers, gravimeters, quantum imaging) — can be *simulated* as a very-low-drift IMU.

## Our concept: DETECT → REMEMBER → RETURN
1. **DETECT** GPS jamming (signal lost / degraded) and spoofing (signal present but false), as fast as possible.
2. **REMEMBER**: while GPS is trusted, the drone records its own map (downward camera snapshots + laser altitude + position) — "breadcrumbs".
3. **RETURN**: after the alarm, navigate with INS + camera + laser, matching current view to its own recorded map, and fly home.

Pitch line: "When GPS is attacked, our drone detects it and flies home using a map it built itself — exactly what the Air Force told us worked in a real case."

## What the Swedish Air Force (Helicopter Wing) told us — use in pitch
- GPS jamming/spoofing happens "really often" (can't give numbers; see news — e.g. Baltic GNSS interference).
- Jamming vs spoofing: depends on the mission → system must handle both.
- Detection must be "as soon as possible".
- Besides GPS they use: **INS (tröghetssystem)**, **camera** a lot, and **maps**. Also zoom camera, **laser altimeter**, **thermal camera**.
- Important for both **short-range and long-range drones** → short range: INS + camera is enough; long range: drift grows, needs map matching.
- Snow problem: objects/landmarks hidden under snow → pre-made maps don't match. Terrain shape (height profile) survives snow; own fresh map also works.
- Real case: a drone lost GPS, **built a map of the ground by itself, and used it to come back**.

## Environment (Den's laptop)
- Windows 11, NVIDIA GPU. User home: `C:\Users\den`.
- Python 3.15 on Windows (if pip wheels fail, use `py install 3.12` and `py -3.12 ...`).
- WSL2 + **Ubuntu 22.04**, user `den`. Enter with `wsl` from PowerShell.
- `C:\Users\den\.wslconfig` has `networkingMode=mirrored` (added Thu evening): WSL had no internet after switching to venue Wi-Fi ("No route to host" when Gazebo downloaded baylands models). Mirrored = WSL shares Windows' network; also lets Windows apps (QGroundControl) reach SITL on localhost. Remove the file + `wsl --shutdown` to undo.
- **PX4-Autopilot** cloned at `~/PX4-Autopilot` (inside Ubuntu), v1.18 beta, `Tools/setup/ubuntu.sh` done, builds fine. Gazebo Harmonic (gz-sim 8).
- Project folder: `C:\Users\den\hackathon\challenge1` (= `/mnt/c/Users/den/hackathon/challenge1` from WSL). `C:\Users\den\hackathon\MyHackApp` is from an old hackathon — ignore.

## Files
- `spoof_detect.py` — 2D simulation, numpy + matplotlib. Drone flies a figure-eight; IMU + GPS fused with a 4-state Kalman filter; slow GPS spoof (0.8 m/s drift) starts at t=60 s.
  - Detector 1: per-sample NIS chi-square test → MISSES slow spoofing (teaching point).
  - Detector 2: windowed mean of whitened innovations (100 samples = 10 s, threshold 13.8) → detects at t≈67.4 s, no false alarm without attack.
  - After alarm: roll back to state before the window, continue IMU-only. Remaining error grows (~80 m at end) due to IMU bias → motivates camera/map backup.
  - Run: `pip install numpy matplotlib` then `python spoof_detect.py` (saves `result.png`).
- `analyze_log.py` — reads a PX4 .ulg log: prints failure injections / failsafes, PX4 reaction time, plots EKF vs ground truth altitude, horizontal error, xy_valid / GPS fix, GPS sample gaps. Run: `py analyze_log.py logs/18_23_09.ulg` → `log_analysis.png`.
- `log_spoof_detect.py` — our detector on real SITL IMU/GPS from the log with an injected slow spoof; compares with a PX4-style 5σ gate, false-alarm check over 50 seeds, delay-vs-spoof-speed sweep. Run: `py log_spoof_detect.py logs/18_23_09.ulg` → `log_spoof_result.png`.
- `logs/18_23_09.ulg` — SITL x500 flight: takeoff 59 s, `gps off` 113 s, `gps ok` 198 s, `gps wrong` 244 s (on ground).
- `FRIEND_START.md` — onboarding for the teammate (setup, what to build: demo dashboard, baylands world, slides).
- Python deps: `pip install numpy matplotlib pyulog`.

## Git workflow
- Private repo: https://github.com/Mattheuszu/eudis-challenge1 (branch `main`). Den's GitHub: `Mattheuszu`. gh CLI at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH in old shells).
- Both teammates work on `main` (48 h hackathon, no PR overhead). Always `git pull` before starting; commit + push after each finished step (working script, new plot, updated slides).
- Avoid conflicts by file ownership: Den = detection / navigation scripts (`spoof_detect.py`, `log_spoof_detect.py`, REMEMBER/RETURN); friend = dashboard, visualisation, slides (new files). Update `CLAUDE.md` Status when something is done.
- New .ulg logs: keep only useful ones in `logs/` (GitHub limit 100 MB per file; 50 MB warns).

## PX4 SITL cheat sheet (inside Ubuntu)
```
pkill -f px4; pkill -f gz          # clean up old sim processes
cd ~/PX4-Autopilot
make px4_sitl gz_x500              # standard drone with GPS
```
In the `pxh>` console (PX4 shell — NOT Linux; ls/cd don't work there):
```
param set NAV_DLL_ACT 0            # disable "No connection to GCS" preflight fail (no QGroundControl)
commander takeoff                  # hovers at 2.5 m
failure gps off                    # simulate jamming (works; SYS_FAILURE_EN already allowed)
failure gps wrong                  # simulate bad/spoofed data
failure gps ok                     # restore
commander land
shutdown                           # or Ctrl+C
```
- Flight logs (.ulg): `~/PX4-Autopilot/build/px4_sitl_default/rootfs/fs/log/<date>/` (note `fs/`). Copy to `challenge1/logs/` and analyse on Windows with `py analyze_log.py logs/<file>.ulg` (pyulog installed). Useful topics: `sensor_gnss` (GPS, logged ~1 Hz), `sensor_combined`, `vehicle_local_position` (EKF, 125 Hz), `vehicle_local_position_groundtruth` (sim truth), `estimator_status_flags`.
- Available models in `Tools/simulation/gz/models`: x500, **x500_flow** (optical flow + laser rangefinder, sim GPS disabled), **x500_mono_cam_down** (downward camera — use for REMEMBER/RETURN), x500_lidar_down, x500_gimbal, x500_vision, x500_depth, etc.
- **Finding:** `gz_x500_flow` in the default world failed: "Number of good matches: 2, desired: 20" → failsafe → Gazebo crashed. The default ground is untextured, so optical flow has nothing to track. This mirrors the snow problem — good pitch point. Fix: textured world, e.g. `PX4_GZ_WORLD=baylands make px4_sitl gz_x500_flow` (or `lawn`; list worlds in `Tools/simulation/gz/worlds`).
- Common user pitfalls: pasting two commands on one line; running Linux commands in PowerShell or in `pxh>`; `wsl --shutdown` must run in PowerShell (from Ubuntu use `wsl.exe --shutdown`).

## Status (Thu 15 Oct, ~20:20)
- [x] Python, WSL/Ubuntu, PX4 + Gazebo installed and working; x500 takes off.
- [x] Interviews with Air Force done (see above).
- [x] Test on x500: `failure gps off` vs `failure gps wrong` (log `logs/18_23_09.ulg`, plot `log_analysis.png`). Results:
  - Both trigger `Failsafe: blind land` exactly ~5.1 s after injection (EKF GPS timeout). PX4 lands in place, does NOT return home.
  - After `gps off` the drone touched down within ~5 s, but the EKF believed it was still at 1.3 m and drifted 6.8 m horizontally in 80 s while sitting on the ground; landing was never detected (stayed armed). Strong pitch point.
  - `gps wrong` in gz SIM only drops fix_type 3→2 (coordinates barely change) → PX4 rejects it as low-quality. It is NOT a realistic spoof (real spoofer keeps a good 3D fix). Also this test ran on the ground (drone had already landed).
- [x] Read .ulg logs in Python (`analyze_log.py`).
- [x] Detector on real SITL data with injected slow spoof: `log_spoof_detect.py` (plot `log_spoof_result.png`). Uses hover segment 20–112.5 s; IMU (sensor_combined rotated by vehicle_attitude to NED, 50 Hz) + GPS (sensor_gnss, ~1 Hz); smooth drag spoof from t=80 s, good 3D fix kept.
  - SITL GPS noise is only ~3 cm and SITL IMU is very good (accel error ~0.008 m/s², ~1.5 m drift in 30 s IMU-only) → we add 1.5 m GPS noise for realism. KF process noise 0.05 m/s² per step (0.3 was far too high: filter absorbed the drift into velocity → nothing detected).
  - Window 20 samples, threshold 18.4 (χ² 99.99 %). 99.9 % / 10 samples gave ~25 % false alarms per run (test repeats each sample).
  - Results (1.5 m noise): spoof 0.5 m/s detected after 12.9 s, PX4-style 5σ per-sample gate never rejects. Delay vs speed: 0.2→21.9 s, 0.3→15.8, 0.5→12.9, 0.8→9.9 (PX4 gate 23.9), 1.5→7.9 (PX4 gate 9.9). ≤0.1 m/s not detected. False alarms 2/50 runs. Final error 12.1 m unprotected vs 5.6 m with detector + IMU-only.
  - Caveat: "PX4 gate" is our imitation of EKF2_GPS_P_GATE; real EKF2 also resets to GPS after rejection timeout. Verify with PX4 ekf2 replay on a spoofed .ulg if time allows.
- [ ] Spoofing injection live in SITL (MAVLink/uORB injector) instead of post-processing.
- [ ] REMEMBER → RETURN demo (start as 2D Python prototype, then x500_mono_cam_down).
- [ ] Optional: very-low-drift "quantum IMU" comparison (change ACC_BIAS) for the quantum-sensor bonus.
- [ ] Slides: Problem (Air Force quotes) → Concept (Detect/Remember/Return) → Demo → Results (detection time vs false alarms, drift with/without backup) → Team. Upload by Sat 12:30.

## Open questions for mentors / lab
- Recorded flight data (IMU/GPS/camera) + Vicon ground truth available?
- Terra lab hours and booking.
- Required detection speed in seconds; typical flight time/distance for short- vs long-range drones; day/night (thermal) needs; desired behaviour after alarm (continue / return / land).
