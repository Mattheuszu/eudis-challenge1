Real-map test of versions C and D (from Guled)
=============================================

Map: REAL heights of Bråviken bay near Norrköping (Kolmården hills in the north,
the flat bay and the Norrköping plain), from AWS Open Data "Terrain Tiles"
(space-radar elevation, NASA SRTM, ~20-30 m detail). 26 x 24.5 km.
The MAGNETIC map is SIMULATED - no detailed free magnetic map exists.

Files
  get_real_map.py      downloads the 30 elevation tiles (2.8 MB) and builds real_map.npz
  real_map.npz         the ready height map (20 m grid) - you don't need to download again
  real_map.png         picture of the map
  real_map_test.py     the test (needs real_map.npz in the same folder)
  real_map_test.png    result picture
  pip install numpy matplotlib
  python real_map_test.py      (~12 min, 175 missions)

Mission (25 random missions per case, random place on the real map)
  A jammer on the target kills GPS within 4 km. A drone starts 1 km outside,
  flies 5 km in, circles the target twice, flies out. Three edge drones hover
  just outside the zone with GPS. On average 21 % of the way in is over water.
  Success = the drone never lost track by more than 50 m.

Versions
  C = terrain matching (laser + real height map) + edge-drone radio ranging
  D = C + MagNav (magnetometer + magnetic map)

Results
  Version     Condition               Success   Max error inside: typical / worst
  IMU only    -                        0 / 25        704 m / 1552 m
  C           normal                  25 / 25          4 m /    5 m
  C           one edge drone lost     25 / 25          6 m /   20 m
  C           radio jammed too         6 / 25        180 m / 1070 m
  D           normal                  25 / 25          4 m /    5 m
  D           one edge drone lost     25 / 25          6 m /   20 m
  D           radio jammed too         8 / 25         71 m /  393 m

What it means
  - With the radio working, C works on real terrain: 25/25, about 4 m.
  - C and D are the same then: the edge drones are already so accurate.
  - Radio jammed too is the hard case: over the real flat bay and plain,
    terrain matching often has nothing to recognise (C: 6/25).
  - MagNav helps exactly there: typical 180 m -> 71 m, worst 1070 m -> 393 m.
    A clear improvement, not a full fix (8/25).
  - Real terrain here is flatter than the simulated hills in sim_long.py,
    so terrain matching alone does worse - an honest real-world finding.

Limits
  - Magnetic map simulated, so MagNav numbers are an estimate.
  - Elevation detail ~20-30 m; the bay edges in the data are coarse.
  - Radio ranging assumes ~3 m accuracy and that the edge drones keep GPS.

Pitch line
  "On a real map of Bråviken, with the radio working, our drones stay within
   5 m in 25 of 25 missions. If the enemy also jams the radio, flat ground and
   water make it hard; adding a magnetometer cuts the error by more than half."
