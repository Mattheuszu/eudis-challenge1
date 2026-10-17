"""Record a live 3-drone mission for the pitch video (slide 8).

Runs mission_demo.py's brain headless, cuts the Gazebo camera between views as the
story unfolds, and saves timestamped frames:
  - Gazebo window screenshots  (gz /gui/screenshot, background thread)
  - our mission map             (the mission app's matplotlib figure)
Then media/make_mission_video.py turns them into the short video.

Start the simulator first (Ubuntu):  bash /mnt/c/Users/den/hackathon/challenge1/sim/start_swarm.sh
Then (PowerShell):                   py media/record_mission.py
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ["DEMO_HEADLESS"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import mission_demo as M  # noqa: E402  (starts drone links + brain state)

OUT = Path(os.environ.get("REC_DIR", ROOT / "media" / "rec"))
GZ_DIR = OUT / "gz"
MAP_DIR = OUT / "map"
MAX_S = 12 * 60          # safety stop
END_AFTER_ALL = 10.0     # keep filming this long after 3/3 on station
MAP_EVERY = 1.0          # s between map frames


def wsl_path(p):
    p = str(p).replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:]


def gz_shot(path):
    try:
        r = subprocess.run(["wsl.exe", "-e", "env", "GZ_IP=127.0.0.1", "gz", "service", "-s", "/gui/screenshot",
                            "--reqtype", "gz.msgs.StringMsg", "--reptype", "gz.msgs.Boolean", "--timeout", "3000",
                            "--req", f'data: "{wsl_path(path)}"'], capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "true" in r.stdout
    except Exception:
        return False


STOP = threading.Event()


def shooter():
    while not STOP.is_set():
        gz_shot(GZ_DIR)               # Gazebo names each picture by wall-clock time


def cam(model, off):
    M.camera.view = "custom"            # stop the app's own chase re-aiming
    M.camera.pending = (model, off)
    M.camera.wake.set()


def chase(i):
    M.camera.view, M.camera.target = "1", i
    M.camera.show(view="1", target=i, yaw=M.drones[i].yaw)


def main():
    GZ_DIR.mkdir(parents=True, exist_ok=True)
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    phases = []                          # (t, phase name) for captions in the edit

    def phase(name):
        phases.append((round(time.time() - M.T0, 2), name))
        print(f"{time.time() - M.T0:6.1f}s  phase: {name}", flush=True)

    print("waiting for drones ...", flush=True)
    while not (M.Ref.lat is not None and all(d.offset for d in M.drones)):
        M.draw(None)
        time.sleep(0.1)
    if not gz_shot(OUT):
        print("WARNING: gz screenshot failed - is the Gazebo window open?", flush=True)
    cam("x500_0", (-30.0, -40.0, 32.0))
    time.sleep(1.5)
    threading.Thread(target=shooter, daemon=True).start()
    phase("overview")
    time.sleep(3)
    M.act("mission")
    t_map = 0.0
    state = "overview"
    t_alarm = t_done = None
    while time.time() - M.T0 < MAX_S + phases[0][0]:
        M.draw(None)
        now = time.time()
        d1 = M.drones[0]
        if state == "overview" and d1.armed and d1.alt > 6:
            state = "chase"; chase(0); phase("scout")
        elif state == "chase" and d1.alarm:
            state = "jammed"; t_alarm = now; phase("jammed")
        elif state == "jammed" and now - t_alarm > 10:
            state = "top"; cam("x500_1", (0.1, 0.0, 95.0)); phase("reroute")
        elif state == "top" and any(d.task == "observe" for d in M.drones):
            state = "target"; cam("target_facility", (-45.0, -45.0, 35.0)); phase("on_station")
        if state == "target" and all(d.task == "observe" for d in M.drones):
            if t_done is None:
                t_done = now; phase("all_on_station")
            elif now - t_done > END_AFTER_ALL:
                break
        if now - t_map > MAP_EVERY:
            t_map = now
            M.fig.savefig(MAP_DIR / f"{now - M.T0:08.2f}.png", dpi=60)
        time.sleep(0.1)
    STOP.set()
    (OUT / "phases.json").write_text(json.dumps({"t0": M.T0, "phases": phases}))
    with M.LOCK:
        (OUT / "events.txt").write_text("\n".join(M.LOG))
    print(f"done: {len(list(GZ_DIR.glob('*.png')))} gazebo frames, {len(list(MAP_DIR.glob('*.png')))} map frames",
          flush=True)
    for d in M.drones:            # leave the drones hovering; land them from mission_demo or stop_swarm.sh
        d.heartbeat_and_sticks()


if __name__ == "__main__":
    main()
