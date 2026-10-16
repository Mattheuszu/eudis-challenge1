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
- Set up a shared GitHub repo + onboarding guide so Guled can work in parallel.

## Fri 16 Oct

### 7. Briefing and networking → new ideas (for future work)
- Satellite company: free satellite imagery as a backup map; drones can share position with each other.
- Another participant: 5G / cell towers as an extra position source.
- → Combined into one message: **multi-source trust check**. Never trust one source; cross-check GPS against IMU, own map, satellite map, other drones, 5G.

- Another participant: companies already sell pre-loaded maps for drones (landmark matching). → Confirms map matching is real and used; sharpened our positioning: **trust layer + fresh own map**, complementary to pre-loaded maps (which can be outdated or snow-covered).

### 8. Guled's GNSS-free navigation sim
- Guled built a sim: IMU-only vs IMU + known checkpoints (279 m → 22 m miss).
- **Finding from it:** with a slightly worse IMU the drone drifts further than the camera can see, misses a checkpoint and is lost. → Breadcrumbs must be **dense relative to IMU drift**; a better (quantum) IMU allows sparser maps.
- → Next: REMEMBER → RETURN with the drone's **own** breadcrumbs.

### 8b. Long-range navigation in snow (Guled, `navigation/sim_long.py`)
- 8.8 km flight without GPS on a snowy day. IMU alone: **1974 m off**. Camera landmarks work on a normal day (16 m) but **in snow the camera recognised 0 of 8 landmarks → 1874 m off** — the Air Force's snow problem, reproduced.
- **Terrain matching** (laser altimeter height profile vs height map; compares *shape*, so a snow layer doesn't matter): **14.5 m** at the destination. Ambiguous matches (flat ground, look-alike hills) are rejected instead of trusted.
- Quantum-sensor bonus: a simulated 40× better accelerometer alone ends **70 m** off — better IMU = fewer fixes needed.

### 9. Interactive live demo (`demo_control.py`, `sim/demo.sdf`)
- Wanted the jury to *see* the problem, not just plots. Built a demo world (START helipad, visible point B) and a control app: fly with the arrow keys, jam GPS with one key, live map + status.
- Measured live: **our GPS monitor reacts in ~1 s, PX4 in ~5 s**. After jamming PX4 either blind-descends or (with a pilot) loses position hold; **return home is impossible without GPS**.
- Breadcrumbs are already recorded and drawn on the map while GPS is trusted → the visual bridge to REMEMBER → RETURN.
- Problem solved on the way: long PX4 status messages arrived split into 50-char pieces → glued them back.

### 10. Jammer hunter — the drones become sensors (Guled)
- Idea: GPS receivers measure interference; closer to the jammer = louder. Two drones without GPS (positions from terrain navigation) log it and locate the jammer.
- **First version was overconfident**: it claimed certainty but was often wrong. Fixed the measurement model; now the real jammer is inside the "95 % sure" area in 9–10 of 10 runs.
- One drone: ~300 m typical, sometimes picks the mirror spot on the other side of its route (2.3 km off). **Two drones: ~120 m typical, worst 224 m.**
- Checked the real basis: PX4 GPS data already has jamming-indicator / noise / AGC fields (real chips fill them; the simulator leaves them at 0).
- → Concept extended: DETECT → REMEMBER → RETURN → **REPORT**.

### 11. Pivot after talking to the military → swarm reroute (`swarm_reroute.py`)
- Military: detection + return-to-base **already exists** for them. They want the swarm to **share the attack and still reach the target**.
- Built DETECT → LOCATE → SHARE → REROUTE: the first jammed drone (scout) broadcasts its interference readings; the swarm estimates where GPS dies and plans around it.
- **First version: drones looped** in and out of the zone. Two causes: (1) one drone's straight track can't tell which side the jammer is on → the "safe" estimate painted almost the whole map as dangerous; (2) the route planner treated the zone as a wall, so a drone at its edge found no way out and flew straight back in. Fixes: danger = cells where GPS dies with > 15 % probability; zone = expensive, not forbidden; never re-enter where GPS really died.
- **Checked it isn't a lucky run:** 8 random jammer positions. Swarm 24/24 drones reach the target vs 21/24 alone; time without GPS 16 s (only the scout) vs 68 s; mission 16 % faster, 17 % less distance. Today's autopilot: 0/3.

### 12. AI mission brain (Guled, `navigation/ai_commander.py`)
- Answer to the military's "find a solution on its own, like an LLM": Claude gets a situation report and can act only through 4 safe tools (circle and measure, plan route, fly route, broadcast). Every call passes a safety check (limits, battery reserve). **The AI decides what; tested code decides how.**
- Detects the jamming *rising* before GPS actually dies, so it acts early.
- Offline run (rule-based brain, same tools): existing system aborts the mission; with the brain the drone locates the jammer, warns the fleet, plans around and **arrives 8 m from the target without ever losing GPS**.
- Without internet or API key it falls back to rules, so the demo never dies.

## Mentor feedback log
| When | Who | What they said | What we changed |
|---|---|---|---|
| Fri | Participant (networking) | "If the spoofer sends a fake but realistic-looking position, how can you tell?" Den had no clear answer. | Prepared the answer: we don't judge whether a position *looks* real, we check it against physics (IMU) and other sources; a spoofer must stay slower than IMU drift to hide, which bounds the damage. Added a short "how we detect spoofing" script for the pitch Q&A. |
| Fri midday | Military (via Guled) | They already have spoofing/jamming detection + return-to-base. Want: inform other drones, swarm finds its own way around to still reach the destination ("like an LLM"). | Pivoted headline to DETECT → LOCATE → SHARE → REROUTE, built `swarm_reroute.py`; LLM positioned as mission advisor, deterministic planner flies. |
| | | | |
