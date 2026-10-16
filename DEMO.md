# Live demo run-sheet

Two live demos:
- **A. Swarm mission at the military base (recommended, ~6 min)** — 3 drones, jammer on the battlefield, target facility. Shows the whole idea: DETECT → ESCAPE → SHARE → REROUTE.
- **B. One drone in the park (~3 min)** — fly with the keys, jam GPS by hand (below, "Start").

## A. Swarm mission (military base)

**Start** (two windows):
1. Ubuntu (type `wsl` in PowerShell first):
   ```
   bash /mnt/c/Users/den/hackathon/challenge1/sim/start_swarm.sh
   ```
   Starts Gazebo with the base world and 3 drones (~2–3 min; laptop gets busy). `... start_swarm.sh 1` = one drone only.
2. New PowerShell (no `wsl`): `cd C:\Users\den\hackathon\challenge1` then `py mission_demo.py`.
   Wait until the status shows D1, D2, D3 (or press START MISSION — it waits until all are ready).
3. Stop everything afterwards (Ubuntu): `bash /mnt/c/Users/den/hackathon/challenge1/sim/stop_swarm.sh`

**What's in the world:** forward operating base (3 launch pads, operators' ground station with people, tents, vehicles, radio tower, concrete barriers), battlefield (ruined house and police station, barriers, crates), **enemy GPS jammer** (truck + antenna; the red dome shows where GPS dies — only for the audience, the drones don't know it) and the **target facility** (collapsed industrial building, yellow ring + beacon).

| Press | What happens (tested live) | Say |
|---|---|---|
| **Cam: overview (5)** | Whole base + battlefield | "Three drones, a reconnaissance target, and somewhere on the way an enemy jammer." |
| **START MISSION (M)** | D1 (scout) takes off, D2 and D3 follow 30 s apart | "The first drone is the scout." |
| (wait ~1–2 min) | D1 flies into the red dome → banner **GPS JAMMED: D1**; log: *GPS LOST → our monitor alarm*, *blind escape along own breadcrumbs*, *BROADCAST danger zone*; D2/D3 *rerouted* | "GPS is gone. Today's autopilot would land blind right here. Ours backs out on its own breadcrumbs — and warns the others." |
| (wait) | Orange no-go circle on the map; D2 and D3 fly around it on GPS; D1 gets GPS back and rejoins | "Only the scout was ever jammed. The others learned from it." |
| (wait) | **ON STATION: 3/3** — drones hover 33–38 m from the target, never inside the building | "Mission complete, all three drones." |
| **Cam: target (6)** / **Cam: chase (1)** + **Tab** | Look at the drones on station / follow each drone | |
| **All home (H)** | Drones fly back around the zone and land on their pads | |

Optional comparison: press **Sharing ON/OFF (N)** *before* START MISSION → each drone has to find the jammer itself (all three get jammed).

Honest notes for the swarm demo: the jamming is simulated by switching a drone's GPS off while it is inside the dome (PX4 failure injection — the drone is not told why); with 3 drones the laptop is busy, so our monitor needs ~2.5–4 s (1 s with one drone); the danger zone the drones share is estimated from where GPS died (no map of the jammer); on a busy laptop the sim runs slower than real time.

---

## B. One drone in the park

## Setup (once per laptop)
- Windows: `pip install numpy matplotlib pyulog pymavlink`
- WSL must use mirrored networking (`C:\Users\<you>\.wslconfig` → `[wsl2]` / `networkingMode=mirrored`, then `wsl --shutdown`).
- Install the demo world (Ubuntu): `bash /mnt/c/Users/den/hackathon/challenge1/sim/install_world.sh`

## Start
1. Ubuntu terminal:
   ```
   pkill -f px4; pkill -f gz
   cd ~/PX4-Autopilot && PX4_GZ_WORLD=demo make px4_sitl gz_x500
   ```
   (Run `cd ~/PX4-Autopilot` first — `make` only works inside that folder.)
   Gazebo opens: drone on the **START** helipad (green flag), red pole with ball = **point B** (~32 m away).
2. Windows PowerShell, project folder: `py demo_control.py` → click the window once (keyboard focus).
   Wait for the green **GPS TRUSTED** banner.

Put Gazebo on the left half of the screen, the demo window on the right.

## Controls (keys or buttons at the bottom of the window)
- **W A S D** or **arrows**: fly North / West / South / East (map directions; takes manual control)
- **R / F** up / down, **Q / E** rotate
- **T** take off · **B** fly to B · **H** fly home to START and land · **L** land here · **G** jam GPS on/off · **X** motors off · **C** clear track · **Esc** quit
- **Camera (Gazebo window):** **1** chase (behind the drone, turns with it) · **2** close · **3** top-down · **4** side · **5** overview

## Story (what to press, what to say)
| Press | What happens | Say |
|---|---|---|
| **T** | Takes off to 5 m | "Normal flight, GPS is trusted." |
| **1** | Camera behind the drone | (looks like a real drone feed) |
| **B** | Flies to B on its own, gold diamonds appear | "While GPS is trusted, the drone records its own path: breadcrumbs." |
| **W A S D** | You fly the drone; release → it stops and holds | "With GPS it holds its position perfectly." |
| **G** | Banner turns red. Our monitor ~1 s, PX4 ~5 s. PX4 starts a **blind descent** | "Now we jam GPS. **We detect it in 1 second, the autopilot needs 5.** And then it just descends wherever it is." |
| **H** | Refused: no position | "It cannot fly home: without GPS it doesn't know where it is. That is what our navigation and swarm sharing solve." |
| **G** then **H** | GPS back → flies to START and lands | "With position, home is easy. Our goal: the same without GPS." |
| **5** | Overview camera | Shows the whole scene: START, B, drone |

Alternative after **G**: press a movement key and release — without GPS the drone keeps sliding instead of stopping ("position hold is gone, the pilot is flying blind").

## Honest notes (if asked)
- Detection here is jamming (signal gone), so 1 s is easy; for slow **spoofing** see `log_spoof_result.png` (0.5 m/s caught in ~13 s, PX4-style check misses it).
- The map shows what the drone **believes**; the real position is in Gazebo.
- Navigation without GPS (terrain matching, 14.5 m after 8.8 km in snow) and the swarm are separate simulations (`navigation/sim_long.py`, `swarm_reroute.py`), not flying in this live simulator yet.
- Occasional `vehicle_imu timestamp error` in the terminal = laptop under load, harmless for the demo.
