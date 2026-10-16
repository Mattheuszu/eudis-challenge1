#!/usr/bin/env bash
# Stop all PX4 instances and Gazebo (run inside Ubuntu/WSL).
pkill -x px4 2>/dev/null
pkill -f "gz sim" 2>/dev/null
pkill -f "ruby.*gz" 2>/dev/null
sleep 1
echo "Simulator stopped."
