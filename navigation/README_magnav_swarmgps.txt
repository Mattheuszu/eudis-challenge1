Two new demos from Guled (for eudis-challenge1)
==============================================

Both are single files, only numpy + matplotlib, no other repo files needed.
  pip install numpy matplotlib


1. magnav_demo.py  - OUTSIDE THE BOX: navigate by the Earth's magnetic field
---------------------------------------------------------------------------
Rocks underground give every place its own small magnetic pattern (the
"crustal anomaly"), mapped by geological surveys. A magnetometer measures it
and the drone matches the pattern to the map, like terrain matching but with
magnetism. It only listens, so there is nothing to jam or spoof; it works at
night, in snow, and over flat land and sea where terrain matching goes blind.

  python magnav_demo.py   -> magnav_result.png   (~1 min)

20 km flight, first half over hills, second half over the sea, 10 runs:
  IMU only                   lost (18.9 km off)
  Terrain matching (laser)   202 m typical, worst 565 m   (blind over the sea: 3 fixes vs 23 on land)
  MagNav (magnetometer)       26 m typical, worst 1077 m  (one bad run)
  Both together               38 m typical, worst 156 m   <- most reliable

Message: "Two maps the enemy can't touch: the shape of the ground and its
magnetism. Where one goes blind, the other still sees."

Honest limits:
  - The magnetic map is simulated and fairly strong (up to ~1000 nT, like ore
    regions). In calm geology the pattern is weaker and accuracy worse.
  - A small drone's motors and electronics disturb a magnetometer; real
    systems mount it away from them and compensate for the drone's own field.
  - Needs a magnetic anomaly map of the area (surveys exist for most of Sweden).


2. swarm_gps_demo.py  - FIXES OUR WEAK SPOT: target INSIDE the jammed area
---------------------------------------------------------------------------
swarm_reroute.py reaches the target by going around the jammer. But the enemy
puts the jammer where it protects something, so often the target is inside.
Edge drones wait just outside the zone (they still have GPS) and measure their
radio distance to the drone inside. Three distances from known points = a
position: the swarm becomes its own GPS, on frequencies the GPS jammer doesn't hit.

  python swarm_gps_demo.py   -> swarm_gps_result.png   (~45 s)

Fly into a 1.5 km jammed zone, circle the target 3 times, fly out, 20 runs:
                                   error while observing   max error inside
  IMU only inside the zone              59 m (worst 134)        202 m
  Swarm GPS: 3 edge drones               1 m (worst 2)            4 m
  One edge drone lost halfway            2 m (worst 2)            4 m
  Bad placement: all on one side         3 m (worst 4)           10 m

Message: "Even inside the jammed area our drones know where they are, because
the swarm becomes its own GPS."

Honest limits:
  - Assumes the drone-to-drone radio still works (GPS jammers target the GPS
    band; a jammer on the datalink band would need relays or terrain/MagNav).
  - Assumes ~3 m radio ranging accuracy (two-way timing); reflections are
    simulated (3 % of ranges) and rejected by a 99.9 % check.
  - Edge drones hover and are visible to the enemy while they do it.
  - Fits with swarm_reroute.py: the swarm already knows where the zone is,
    so it can place the edge drones around it automatically.
