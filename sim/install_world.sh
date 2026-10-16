#!/usr/bin/env bash
# Copy our demo world into PX4 (run inside Ubuntu/WSL):
#   bash /mnt/c/Users/den/hackathon/challenge1/sim/install_world.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cp "$HERE/demo.sdf" ~/PX4-Autopilot/Tools/simulation/gz/worlds/demo.sdf
echo "Installed. Start with:"
echo "  cd ~/PX4-Autopilot && PX4_GZ_WORLD=demo make px4_sitl gz_x500"
