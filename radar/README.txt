Jamming Radar - flight-radar style replay of swarm_reroute.py
==============================================================

OPEN IT: double-click jamming_radar.html (any browser, works offline,
the simulation data is built into the page).

What it shows (all from Den's swarm_reroute.py, nothing invented):
  - drones as aircraft with callsigns (SCOUT-1, UAV-2, UAV-3), trails and
    live status; red dashed trail + pulsing ring = flying without GPS
  - GPS interference reports as coloured cells (green low, yellow degraded,
    red = GPS lost), like public GPS-jamming maps built from aircraft reports
  - the swarm's shared danger map (orange) as it updates
  - the real jammer and GPS-dead zone (toggle: hidden from the drones)
  - side panel: status, navigation source, km flown, seconds without GPS,
    event feed
  - switch "Standard autopilot" (0/3 reach target) vs "Our swarm" (3/3)
  - timeline: Play / scrub / speed 5x 15x 40x, space bar = play/pause

Files:
  jamming_radar.html   the page (open this)
  radar_data.json      the same simulation data as a separate file
  export_radar.py      regenerates radar_data.json from swarm_reroute.py:
                         python export_radar.py   (put it next to swarm_reroute.py)
                       To refresh the page after changing the simulation,
                       paste the new JSON into jamming_radar.html after
                       "window.RADAR_DATA = " (or ask Claude to rebuild it).

Limit: no real map underneath (radar grid only). Simulation, not real flights.
