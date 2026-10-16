#!/usr/bin/env bash
# Copy our worlds into PX4 (run inside Ubuntu/WSL):
#   bash /mnt/c/Users/den/hackathon/challenge1/sim/install_world.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
for w in demo base; do
  cp "$HERE/$w.sdf" ~/PX4-Autopilot/Tools/simulation/gz/worlds/$w.sdf
done
echo "Installed worlds: demo (park, 1 drone), base (military base + battlefield)."
echo "  1 drone:  cd ~/PX4-Autopilot && PX4_GZ_WORLD=base make px4_sitl gz_x500"
echo "  3 drones: bash $HERE/start_swarm.sh"
