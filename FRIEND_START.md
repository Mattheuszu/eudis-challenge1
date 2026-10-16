# Start here (for the teammate and their Claude Code)

You are joining Den's EUDIS Defence Hackathon project (Challenge 1, GNSS-denied navigation).
**Read `CLAUDE.md` first**: it has the event, deadlines, concept, Air Force interview, results and status.
Paths in `CLAUDE.md` are from Den's laptop (`C:\Users\den\...`); use wherever you unzipped this folder instead.

## 1. Setup (10 min, Windows)

Get the code (private repo — Den must add you as a collaborator first, accept the email invite):
```
git clone https://github.com/Mattheuszu/eudis-challenge1.git
cd eudis-challenge1
pip install numpy matplotlib pyulog pymavlink
```
(Got this as a zip instead? Unzip it anywhere and work in that folder; it is a snapshot of the repo.)

Git routine (see "Git workflow" in `CLAUDE.md`): `git pull` before you start, commit + push small steps often, work in your own new files.
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
| `demo_control.py` + `sim/demo.sdf` → `demo_screenshot.png` | **Live demo**: fly the PX4 drone with arrow keys, jam GPS with G. World with START helipad and point B. Our monitor ~1 s vs PX4 ~5 s; return home impossible without GPS. Run-sheet: `DEMO.md` |
| `swarm_reroute.py` → `swarm_reroute.png`, `swarm_reroute.gif` | **New headline after military feedback: DETECT → LOCATE → SHARE → REROUTE.** Scout drone gets jammed and shares; swarm plans around. 8 random runs: swarm 24/24 reach target vs 21/24 alone, 16 s vs 68 s without GPS, 16 % faster; today's autopilot 0/3 |
| `JOURNEY.md` | Process log for the jury (30 % of score): every step, failures and fixes, mentor feedback table |

Key numbers for slides are in `CLAUDE.md` → Status and "Ideas collected Fri". **Pitch headline changed:** the military already has detect + return home; our new claim is "one drone jammed, the whole swarm learns" (see `CLAUDE.md` → MILITARY FEEDBACK).

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

## 3a. Your files are in the repo now
`sim_long.py`, `jammer_hunt.py`, their plots and README are in `navigation/` (added by Den from your zip, credited to you). Still missing: `ai_commander.py`, `gnss_free_nav.py`, the pitch deck — send them the same way, or push them yourself (below).

## 3b. Put your work into the shared repo (do this now)

Your `gnss_free_nav.py`, `sim_long.py`, `jammer_hunt.py`, their plots/GIF and the pitch deck should be in the repo **under your name**: the commit history is proof of teamwork (20 % of the score), and Den's Claude can then check that the slide numbers match the results.

1. Accept the GitHub invite (email from GitHub, repo `Mattheuszu/eudis-challenge1`).
2. Clone it next to your current folder, copy your files in, then:
   ```
   git config user.name "<your name>"
   git config user.email "<your github email>"
   git pull
   git add gnss_free_nav.py sim_long.py jammer_hunt.py jammer_hunt.png <deck file>
   git commit -m "Add GNSS-free navigation sim, jammer hunter and pitch deck"
   git push
   ```
   (The GIF can be large; skip it if it is over ~20 MB.)
3. From then on: `git pull` before you start, `git push` after each finished step.

Pitch numbers to keep consistent with Den's results: jamming detected by our monitor in ~1 s vs PX4 ~5 s; slow spoof 0.5 m/s caught in ~13 s, PX4-style check misses it; jammer hunter **~120 m typical (10 runs)** rather than the best run 71 m.

## 4. Prompt to paste into your Claude Code

> Read CLAUDE.md and FRIEND_START.md in this folder. I'm Den's teammate, I own visualisation, the demo dashboard and slides. First regenerate the three plots to check my setup, then help me build a demo dashboard that replays logs/18_23_09.ulg as an animation with a top-down map and a GPS TRUSTED / SPOOFING DETECTED status. Explain things simply, I'm a beginner.
