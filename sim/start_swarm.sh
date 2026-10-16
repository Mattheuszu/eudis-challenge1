#!/usr/bin/env bash
# Start the "base" world with N drones (default 3) - run inside Ubuntu/WSL:
#   bash /mnt/c/Users/den/hackathon/challenge1/sim/start_swarm.sh        # 3 drones
#   bash /mnt/c/Users/den/hackathon/challenge1/sim/start_swarm.sh 1      # just one (lighter laptop)
# Stop everything:  bash /mnt/c/Users/den/hackathon/challenge1/sim/stop_swarm.sh
# Drone i listens for MAVLink on UDP 18570+i (system id i+1); demo_control.py connects to all of them.
set -e
N=${1:-3}
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/install_world.sh" > /dev/null
bash "$HERE/stop_swarm.sh" > /dev/null 2>&1 || true
cd ~/PX4-Autopilot

POSES=("0,0" "0,6" "0,-6")           # launch pads, Gazebo x East, y North (matches sim/base.sdf)
mkdir -p /tmp/swarm
for ((i = 0; i < N; i++)); do
  echo "Starting drone $((i + 1)) at pad (${POSES[$i]}) ..."
  PX4_SYS_AUTOSTART=4001 PX4_SIM_MODEL=gz_x500 PX4_GZ_WORLD=base PX4_GZ_MODEL_POSE="${POSES[$i]}" \
    nohup ./build/px4_sitl_default/bin/px4 -i "$i" -d > "/tmp/swarm/px4_$i.log" 2>&1 &
  if [ "$i" -eq 0 ]; then
    # the first drone starts Gazebo; wait until its model is in the world (first run downloads models)
    for _ in $(seq 1 180); do
      grep -q "Startup script returned\|gz_bridge.*model" "/tmp/swarm/px4_0.log" 2>/dev/null && break
      sleep 2
    done
  else
    sleep 8
  fi
done
echo
echo "Running $N drone(s). Logs: /tmp/swarm/px4_<i>.log"
echo "Now on Windows (PowerShell):  cd C:\\Users\\den\\hackathon\\challenge1  ;  py mission_demo.py"
