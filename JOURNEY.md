# Our journey: what we tried, what failed, what we learned

Process log for the jury and mentors (30 % of the score is process).
Each step: what we did → what happened → what we learned / changed.
Evidence: commits in this repo, plots, flight logs in `logs/`.

## Thu 15 Oct

### 1. Talked to the users first
- Interviewed the Swedish Air Force (Helicopter Wing) before writing code.
- Learned: jamming/spoofing happens "really often"; detection must be "as soon as possible"; they rely on INS, camera, maps, laser altimeter; snow hides landmarks; a real drone once **built its own map and used it to come back**.
- → Our concept **DETECT → REMEMBER → RETURN** comes straight from this.

### 2. Toy model to understand the problem (`spoof_detect.py`)
- 2D drone + IMU + GPS + Kalman filter, slow spoof.
- **Finding:** a standard per-measurement check (NIS χ²) *misses* a slow spoof. A check over a 10 s window catches it.
- After the alarm, IMU-only error still grows → motivates the camera/map step.

### 3. Tested the real autopilot (PX4 + Gazebo simulator)
- `failure gps off` (jamming) → PX4 reacts after **5.1 s**, then **blind-lands where it is**. It does not fly home.
- In one run the drone sat on the ground while PX4 believed it was still flying at 1.3 m and 6.8 m away.
- **Repeated the test** in a second world: reaction **5.06 s** again (solid), but this time it detected the landing. → We only claim what reproduced.
- `failure gps wrong` turned out **not to be a realistic spoof**: it just lowers the fix quality, so PX4 easily rejects it. A real spoofer keeps a good fix. → We had to build our own spoof injection.

### 4. Optical-flow drone failed on plain ground
- `x500_flow` (camera-based navigation) crashed in the default world: "2 good matches, 20 needed". The ground has no texture.
- → Same problem as **snow** that the Air Force described. Fixed by a textured world (`baylands`). Good pitch point: vision needs texture or terrain shape.

### 5. Our detector on real flight data (`log_spoof_detect.py`)
- Took real IMU + GPS from the PX4 flight and injected a slow, smooth spoof that keeps a good 3D fix.
- **First attempt detected nothing.** Cause: we told the filter the IMU was 50× worse than it is, so it explained the spoof as real motion. → Measured the real IMU error against ground truth (0.008 m/s²) and fixed the model.
- **Second attempt: 25 % false alarms.** Cause: the test repeats every second, so rare events add up. → Longer window (20 s) + stricter threshold (99.99 %). Now 2/50.
- Simulator GPS is unrealistically clean (3 cm). → Added realistic 1.5 m noise and reported both.
- **Result:** 0.5 m/s spoof detected in **12.9 s**; PX4-style check never notices. Error 12.1 m unprotected vs 5.6 m with our detector. Spoofs slower than 0.2 m/s are not detected (honest limit).

### 6. Infrastructure problems we solved
- Simulator lost internet after switching to venue Wi-Fi → switched WSL to mirrored networking.
- Set up a shared GitHub repo + onboarding guide so the teammate can work in parallel.

## Fri 16 Oct

### 7. Briefing and networking → new ideas (for future work)
- Satellite company: free satellite imagery as a backup map; drones can share position with each other.
- Another participant: 5G / cell towers as an extra position source.
- → Combined into one message: **multi-source trust check**. Never trust one source; cross-check GPS against IMU, own map, satellite map, other drones, 5G.

### 8. Teammate's GNSS-free navigation sim
- Teammate built a sim: IMU-only vs IMU + known checkpoints (279 m → 22 m miss).
- **Finding from it:** with a slightly worse IMU the drone drifts further than the camera can see, misses a checkpoint and is lost. → Breadcrumbs must be **dense relative to IMU drift**; a better (quantum) IMU allows sparser maps.
- → Next: REMEMBER → RETURN with the drone's **own** breadcrumbs.

## Mentor feedback log
| When | Who | What they said | What we changed |
|---|---|---|---|
| | | | |
