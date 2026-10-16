# Live demo run-sheet (≈3 min)

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
- RETURN by breadcrumbs is shown as a 2D prototype (in progress), not yet flying in this simulator.
- Occasional `vehicle_imu timestamp error` in the terminal = laptop under load, harmless for the demo.
