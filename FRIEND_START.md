# Start here (for the teammate and their Claude Code)

You are joining Den's EUDIS Defence Hackathon project (Challenge 1, GNSS-denied navigation).
**Read `CLAUDE.md` first**: it has the event, deadlines, concept, Air Force interview, results and status.
Paths in `CLAUDE.md` are from Den's laptop (`C:\Users\den\...`); use wherever you unzipped this folder instead.

## 1. Setup (10 min, Windows)

```
pip install numpy matplotlib pyulog
```
(If Python 3.15 wheels fail: `py install 3.12`, then use `py -3.12 -m pip ...` and `py -3.12 script.py`.)

Check everything works by regenerating the three plots:
```
python spoof_detect.py                         # -> result.png
python analyze_log.py logs/18_23_09.ulg        # -> log_analysis.png
python log_spoof_detect.py logs/18_23_09.ulg   # -> log_spoof_result.png (takes ~1 min)
```

PX4 + Gazebo simulator (only needed for the 3D demo): WSL2 + Ubuntu 22.04, then
```
git clone https://github.com/PX4/PX4-Autopilot.git --recursive ~/PX4-Autopilot
bash ~/PX4-Autopilot/Tools/setup/ubuntu.sh      # then restart WSL
cd ~/PX4-Autopilot && make px4_sitl gz_x500
```
See the "PX4 SITL cheat sheet" in `CLAUDE.md` for the `pxh>` commands.

## 2. What exists so far

| File | What it shows |
|---|---|
| `spoof_detect.py` → `result.png` | Toy 2D sim: simple check misses slow spoofing, our window detector catches it |
| `analyze_log.py` → `log_analysis.png` | Real PX4 log: after GPS loss PX4 blind-lands in ~5 s, never returns home; EKF thinks it is at 1.3 m while on the ground, drifts 6.8 m |
| `log_spoof_detect.py` → `log_spoof_result.png` | Our detector on real PX4 IMU/GPS + injected slow spoof: 0.5 m/s caught in 12.9 s, PX4-style gate misses it; 2/50 false alarms |

Key numbers for slides are in `CLAUDE.md` → Status.

## 3. Your tasks (visualisation, demo, slides)

1. **Slides draft for Checkpoint 2 (Fri 13:00).** Structure: Problem (Air Force quotes) → Concept DETECT / REMEMBER / RETURN → Demo → Results (the plots above) → Team. Final upload Sat 12:30, pitch 5 min.
2. **Nicer simulator world.** Default world is a grey plane (also breaks camera/optical flow). Try:
   ```
   PX4_GZ_WORLD=baylands make px4_sitl gz_x500_mono_cam_down
   ```
   Worlds list: `~/PX4-Autopilot/Tools/simulation/gz/worlds`.
3. **Live demo dashboard (Python, matplotlib or similar)** to show next to Gazebo:
   - top-down map: true path, what GPS says, where the drone thinks it is;
   - big status: green `GPS TRUSTED` → red `SPOOFING DETECTED`;
   - later: downward camera view + match with recorded "breadcrumbs".
   Start by replaying `logs/18_23_09.ulg` (reuse the loading code from `log_spoof_detect.py`) as an animation; live connection to PX4 (MAVLink via `pymavlink`) can come later.
4. **Record videos as backup**: "without protection" vs "with our system", side by side.

Den is building the REMEMBER → RETURN logic (2D prototype) in parallel; don't edit `log_spoof_detect.py` / `spoof_detect.py` without telling him, make new files instead.

## 4. Prompt to paste into your Claude Code

> Read CLAUDE.md and FRIEND_START.md in this folder. I'm Den's teammate, I own visualisation, the demo dashboard and slides. First regenerate the three plots to check my setup, then help me build a demo dashboard that replays logs/18_23_09.ulg as an animation with a top-down map and a GPS TRUSTED / SPOOFING DETECTED status. Explain things simply, I'm a beginner.
