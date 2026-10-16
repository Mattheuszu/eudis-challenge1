# Jury Q&A cheat sheet

Short answers (2–3 sentences). Say the number, say the limit, stop. Who answers: **D** = Den, **G** = Guled.

## The big ones

**"Isn't this all just simulation?"** (D)
Yes, and we say so on the slides. But it's the real PX4 autopilot (the software on real military and commercial drones), three of them flying live in Gazebo, our detector ran on real PX4 flight data, and navigation was re-tested on the real height map of Bråviken. Next step: the Holybro PX4 drones in Terra lab here at LiU.

**"What if the enemy jams the drones' radio link too?"** (G)
Then sharing stops and each drone is on its own: it still detects in 1 s and retraces its own breadcrumbs. On the real Bråviken map, terrain matching alone then works in 6 of 25 missions; MagNav cuts the error from 180 m to 71 m. That's our biggest open problem and we show it.

**"The military already has detection and return-to-base. What's new?"** (D)
They told us that themselves. What's new is the swarm: one drone gets jammed, the others learn and still reach the target — 24 of 24 vs 0 of 3 today. Plus we secured that sharing against a captured drone.

**"Why not just buy an anti-jam antenna (CRPA)?"** (D)
Antennas help a lot against jamming (and partly against spoofing), but they are heavy, expensive and power-hungry for small drones. Ours is software only, runs on drones that already exist, and works together with an antenna.

**"Who would buy this? Business model?"** (G)
Armed forces and drone makers building on PX4; in Sweden procurement goes via FMV. It's a software module, so a licence per drone or per fleet, and it's dual use: civil drones and aviation in the jammed Baltic.

## Detection

**"How do you detect spoofing if the fake position looks real?"** (D)
We don't judge whether the position looks real; we compare GPS with the drone's own motion sensors. GPS noise is random, a spoofer always pushes one way, and our 20-second window catches that push: 0.5 m/s in 13 s.

**"What spoofing can't you detect?"** (D)
Very slow drags below about 0.1 m/s. But to stay hidden the spoofer must stay that slow, which limits how far it can drag the drone.

**"False alarms?"** (D)
2 in 50 runs without attack on real flight data. After an alarm the drone falls back to its own sensors; it doesn't crash.

## Swarm and security

**"How do you stop a fake warning from a captured drone?"** (D)
Drones share measurements, never commands. A warning is cheap to believe; an all-clear must be proven: whoever says "all quiet" where another drone really lost GPS is exposed. Liar caught 6 of 6, no honest drone rejected.

**"What about a smarter liar?"** (D)
A liar that stays inside normal noise can't be caught by physics alone, but it also can't do much harm. Before any drone has lost GPS, an all-clear can't be disproved yet; that's a known limit.

**"Does the AI fly the drone?"** (G)
No. The AI decides what (measure, plan, warn); tested code decides how, and every action passes a safety check (battery reserve, limits). The slide shows the rule-based mode, which uses the same tools.

## Navigation

**"Doesn't snow break map matching?"** (G)
Snow breaks camera landmarks (0 of 8 recognised in our sim), but not the shape of the hills. A laser altimeter compares height profiles: 14.5 m after 8.8 km in snow.

**"What about flat ground or sea?"** (G)
That's where terrain matching is weak; our real-map test showed it. That's why we add MagNav (the Earth's magnetic map, which can't be jammed) and drone-to-drone ranging.

**"How accurate is the jammer location?"** (G)
About 120 m typical with two drones over 10 runs, worst 224 m. The best single run was 71 m, but we quote the typical value.

## If something goes wrong on stage
- GIF doesn't play: the first frame already shows the end result. Keep talking.
- Over time: say slide 10 in one sentence and skip to slide 12.
