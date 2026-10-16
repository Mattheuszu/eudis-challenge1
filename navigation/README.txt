GNSS hackathon - long-range navigation and jammer hunter
========================================================

Files (keep both in the same folder):
  sim_long.py     8.8 km flight without GPS in snow: IMU only vs camera vs
                  terrain matching (laser altimeter + height map).
  jammer_hunt.py  Two drones without GPS locate a hidden jammer from how loud
                  the jamming is. Uses sim_long.py.

Setup (once):
  pip install numpy matplotlib

Run:
  python sim_long.py                 -> sim_long_result.png   (~10 s)
  python jammer_hunt.py --no-gif     -> jammer_hunt.png       (~25 s)
  python jammer_hunt.py              -> also jammer_hunt.gif  (a few minutes)

Settings to play with are the UPPERCASE values at the top of each file.
Both files can be imported without running anything, so other scripts can
reuse their functions (e.g. import sim_long as S; S.fly(use_terrain=True)).

All results are simulation (simulated terrain and jamming), not real flights.
