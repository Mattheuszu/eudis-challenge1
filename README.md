# GPS Under Attack — one drone gets jammed, the whole swarm learns

🥈 **2nd place, Challenge 1 (GNSS-denied navigation) — EUDIS Defence Hackathon 2026, Linköping, Sweden (15–17 Oct 2026)**

Team: **Den** (cyber security) · **Guled** (computer engineering)

## The problem
GPS jamming and spoofing happen "really often" (Swedish Air Force, Helicopter Wing). We tested the PX4 autopilot: after GPS loss it needs ~5 s, then lands blind wherever it is. Military end-users told us detect-and-return already exists — what's missing is a swarm that **warns each other and still completes the mission**.

## What we built (in 48 hours)
| Step | What | Result (simulation) |
|---|---|---|
| **Detect** | GPS monitor + windowed IMU-vs-GPS consistency test | jamming in **1 s** (PX4: 5 s); slow 0.5 m/s spoof in **13 s** on real PX4 flight data |
| **Navigate** | terrain matching with a laser altimeter (snow doesn't change the shape of the hills) | **14.5 m** off after 8.8 km in snow (IMU only: 1974 m); real Bråviken terrain 25/25 missions within 50 m |
| **Locate** | drones as sensors: GPS interference readings → jammer position | ~**120 m** with two drones |
| **Decide** | AI mission brain: the AI decides *what*, tested code decides *how*, safety check on every action | mission completed 8 m from target (rule-based mode) |
| **Share + reroute** | the jammed scout shares its measurements, the swarm plans around the danger zone | **24/24** drones reach the target over 8 random runs (today's autopilot: 0/3) |
| **Secure** | defence against fake reports from a captured drone: "a warning is cheap to believe, an all-clear must be proven" | liar caught **6/6**, 0 honest drones rejected |

**Live proof:** 3 real PX4 autopilots in Gazebo — the scout is jammed, alarm after 1.0 s, it backs out on its own breadcrumbs, the others fly around: 3/3 on station (`media/gazebo_mission.mp4`).

Bonus ideas we simulated: swarm as its own GPS for targets inside the jammed zone (59 m → 1 m), MagNav (magnetic map navigation over the sea), a quantum-grade accelerometer (70 m instead of 2 km after 8.8 km).

## Honest limits
Simulation only so far (real PX4 autopilot software, not real flights) · the swarm needs its drone-to-drone radio link · simple free-space jammer model · very slow spoofs (< 0.1 m/s) are not caught.

## Repository
- `pitch/` — pitch deck (`GPS_Under_Attack_pitch.pptx`), Q&A notes
- `JOURNEY.md` — what we tried, what failed, what we changed
- `SHOWCASE_standalone.html` — one-page overview of every result
- Detection: `spoof_detect.py`, `log_spoof_detect.py`, `analyze_log.py`
- Swarm: `swarm_reroute.py`, `swarm_attack.py`, live mission `mission_demo.py` + `sim/` (Gazebo world, start scripts)
- Navigation, jammer hunter, AI brain, MagNav, real-terrain test: `navigation/` (Guled)
- Flight-radar style replay: `radar/` (Guled)

Run any simulation with `pip install numpy matplotlib pyulog`, then `python <script>.py`. The live demo needs PX4 SITL + Gazebo Harmonic (see `DEMO.md`).
