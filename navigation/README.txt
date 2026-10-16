Teammate's files for eudis-challenge1
====================================

Keep all four .py files in the same folder.

  gnss_free_nav.py  IMU only vs IMU + camera checkpoints (300 m route).
                    IMU only misses by ~279 m, with checkpoints ~22 m.
  sim_long.py       8.8 km flight without GPS in snow: IMU only vs camera vs
                    terrain matching (laser altimeter + height map).
                    Needed by jammer_hunt.py and ai_commander.py.
  jammer_hunt.py    Two drones without GPS locate a hidden jammer from how loud
                    the jamming is. 10 runs: ~120 m typical, worst 224 m.
  ai_commander.py   Mission brain for one drone: detects jamming, circles to
                    locate the jammer, broadcasts a warning, plans its own route
                    around the danger zone (A*), completes the mission.
                    Brain = Claude (needs ANTHROPIC_API_KEY + pip install anthropic)
                    or an offline rule-based brain (--offline). Every action
                    passes a safety check; the AI chooses, tested code flies.

Setup (once):
  pip install numpy matplotlib
  pip install anthropic          (only for ai_commander.py with Claude)

Run:
  python gnss_free_nav.py               -> result.png  (NOTE: same name as
                                           spoof_detect.py's plot - rename the
                                           output if both live in one folder)
  python sim_long.py                    -> sim_long_result.png   (~10 s)
  python jammer_hunt.py --no-gif        -> jammer_hunt.png       (~25 s)
  python ai_commander.py --offline      -> ai_mission.png, ai_mission_log.txt (~30 s)

Settings to play with are the UPPERCASE values at the top of each file.
All results are simulation (simulated terrain and jamming), not real flights.
