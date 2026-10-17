"""Live swarm mission on the military-base world: DETECT -> ESCAPE -> SHARE -> REROUTE.

Three real PX4 drones (SITL) fly from the forward operating base to observe an
enemy facility. A GPS jammer sits on the way (red dome in Gazebo). The first
drone to fly in loses GPS: our monitor reacts in ~1 s, the drone backs out
blind along its own breadcrumbs, and the danger zone is shared - the others
fly around it. All drones stop at a safe stand-off point next to the target,
never inside the building.

Start the simulator first (Ubuntu):
    bash /mnt/c/Users/den/hackathon/challenge1/sim/start_swarm.sh        (3 drones)
Then on Windows:
    py mission_demo.py

Buttons do everything; keys work when this window has focus:
    M  start swarm mission      H  all home          L  land all       N  sharing on/off
    T  take off drone 1         J  jam drone 1 on/off
    W A S D / arrows  fly drone 1 (map directions)   R / F up / down   Q / E rotate
    1-5  camera view (chase, close, top, side, overview)   Tab  camera on next drone   6  camera on target
    Esc  quit
The jamming is simulated: the app switches a drone's GPS off while it is inside the red dome
(PX4 failure injection), exactly like a real jammer would - the drone itself is not told why.
"""
import math
import os
import socket
import struct
import subprocess
import threading
import time
from collections import deque

import matplotlib

matplotlib.use("Agg" if os.environ.get("DEMO_HEADLESS") else "TkAgg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.widgets import Button  # noqa: E402
from pymavlink import mavutil  # noqa: E402

# ---------------- SCENE (must match sim/base.sdf; map frame = metres North, East of pad 1) ----------------
N_DRONES = int(os.environ.get("N_DRONES", "3"))
PADS = [(0.0, 0.0), (6.0, 0.0), (-6.0, 0.0)]            # (north, east) launch pads
TARGET = (-15.0, 109.0)                                  # enemy facility (north, east)
JAMMER = (-7.0, 50.0)                                    # jammer truck (north, east) - unknown to the drones
JAM_RADIUS = 20.0                                        # m, GPS dies inside this sphere (red dome)
CRUISE_ALT = 12.0                                        # m above the pads
STANDOFF = 26.0                                          # m from the target centre: observe, don't touch
FORMATION = 10.0                                         # m between drones on station
LAUNCH_GAP = 30.0                                        # s between launches (drone 1 = scout)
NOGO_RADIUS = 26.0                                       # m, assumed danger zone (typical jammer reach + margin)
NOGO_AHEAD = 16.0                                        # m, GPS died while flying this way -> danger lies ahead
GPS_SILENT_LIMIT = 1.0                                   # s -> our monitor raises the alarm
ESCAPE_BACK = 22.0                                       # m back along the drone's own breadcrumbs
STICK = 500
COLORS = ["#2a6fdb", "#8a63d2", "#1a9e8f"]
GZ_MODELS = [f"x500_{i}" for i in range(N_DRONES)]
CAMERA_VIEWS = {"1": "Chase", "2": "Close", "3": "Top-down", "4": "Side", "5": "Overview"}
# --------------------------------------------------------------------------------------------------

for key in [k for k in plt.rcParams if k.startswith("keymap.")]:
    plt.rcParams[key] = []

PX4_MAIN = {1: "MANUAL", 2: "ALTITUDE", 3: "POSITION", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED"}
PX4_AUTO = {1: "READY", 2: "TAKEOFF", 3: "HOLD", 4: "MISSION", 5: "RETURN", 6: "LAND", 20: "BLIND DESCENT"}
R_EARTH = 6378137.0
LOG = deque(maxlen=12)
T0 = time.time()
LOCK = threading.Lock()


def log(text):
    with LOCK:
        LOG.append(f"{time.time() - T0:5.0f}s  {text}")


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(v):
    n = math.hypot(*v) or 1.0
    return (v[0] / n, v[1] / n)


# observation points: stand-off on the side facing the base, spread sideways
_dir = unit(TARGET)                                      # from base towards target
_side = (-_dir[1], _dir[0])
OBS_CENTRE = (TARGET[0] - STANDOFF * _dir[0], TARGET[1] - STANDOFF * _dir[1])
OBS = [(OBS_CENTRE[0] + k * FORMATION * _side[0], OBS_CENTRE[1] + k * FORMATION * _side[1]) for k in (0, 1, -1)]


class Ref:
    """Common map origin = pad 1, from drone 1's first home position."""
    lat = lon = alt = None

    @classmethod
    def ned(cls, lat, lon):
        return (math.radians(lat - cls.lat) * R_EARTH,
                math.radians(lon - cls.lon) * R_EARTH * math.cos(math.radians(cls.lat)))

    @classmethod
    def latlon(cls, n, e):
        return (cls.lat + math.degrees(n / R_EARTH),
                cls.lon + math.degrees(e / (R_EARTH * math.cos(math.radians(cls.lat)))))


class Drone:
    def __init__(self, i):
        self.i, self.sysid, self.name, self.color = i, i + 1, f"D{i + 1}", COLORS[i % 3]
        self.m = mavutil.mavudp("127.0.0.1:0", input=False, source_system=255, source_component=190)
        self.m.destination_addr = ("127.0.0.1", 18570 + i)     # PX4 instance i (see start_swarm.sh)
        if hasattr(socket, "SIO_UDP_CONNRESET"):    # Windows: don't kill the socket if the drone isn't up yet
            self.m.port.ioctl(socket.SIO_UDP_CONNRESET, False)
        self.connected = self.armed = self.setup_done = False
        self.mode = "?"
        self.local = (0.0, 0.0)
        self.offset = None                      # map = local + offset (each PX4 starts at its own pad)
        self.alt = self.vn = self.ve = self.yaw = 0.0
        self.last_good_gps = None
        self.gps_dts = deque(maxlen=30)
        self.gps_fix = 0
        self.takeoff_tries, self.takeoff_at = 0, 0.0
        self.jam_on = False                     # scene: is the jammer cutting this drone's GPS?
        self.alarm = False                      # our monitor: GPS silent
        self.task, self.wps, self.sent_wp, self.sent_at = "idle", [], None, 0.0
        self.launch_at = None
        self.escape_to = self.escape_until = None
        self.gps_back_at = None
        self.track, self.blind_track, self.crumbs = ([], []), ([], []), []
        self.sticks = (0, 0, 500, 0)
        self._chunk = ""
        threading.Thread(target=self._rx, daemon=True).start()

    # ---- position in the shared map frame ----
    @property
    def pos(self):
        if self.offset is None:
            return PADS[self.i]
        return (self.local[0] + self.offset[0], self.local[1] + self.offset[1])

    def gps_ok(self, now):
        # silent longer than 3 normal GPS intervals (min GPS_SILENT_LIMIT): with 3 drones the laptop
        # is busy and GPS messages arrive irregularly - a fixed 1 s caused false alarms
        dts = sorted(self.gps_dts)
        limit = max(GPS_SILENT_LIMIT, 3 * dts[len(dts) // 2]) if dts else 2.0
        return self.last_good_gps is not None and now - self.last_good_gps < limit

    def _rx(self):
        while True:
            try:
                msg = self.m.recv_match(blocking=True, timeout=0.5)
            except OSError:          # drone not running (yet) - keep listening
                time.sleep(0.5)
                continue
            if msg is None or msg.get_srcSystem() != self.sysid:
                continue
            t = msg.get_type()
            with LOCK:
                if t == "HEARTBEAT" and msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_PX4:
                    self.connected = True
                    self.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                    main, sub_ = (msg.custom_mode >> 16) & 0xFF, (msg.custom_mode >> 24) & 0xFF
                    self.mode = PX4_AUTO.get(sub_, f"AUTO-{sub_}") if main == 4 else PX4_MAIN.get(main, str(main))
                elif t == "HOME_POSITION" and Ref.lat is None and self.i == 0:
                    Ref.lat, Ref.lon, Ref.alt = msg.latitude / 1e7, msg.longitude / 1e7, msg.altitude / 1000.0
                elif t == "LOCAL_POSITION_NED":
                    self.local, self.alt, self.vn, self.ve = (msg.x, msg.y), -msg.z, msg.vx, msg.vy
                elif t == "GLOBAL_POSITION_INT" and Ref.lat is not None and self.offset is None and self.gps_fix >= 3:
                    g = Ref.ned(msg.lat / 1e7, msg.lon / 1e7)
                    self.offset = (g[0] - self.local[0], g[1] - self.local[1])
                elif t == "ATTITUDE":
                    self.yaw = msg.yaw
                elif t == "GPS_RAW_INT":
                    self.gps_fix = msg.fix_type
                    if msg.fix_type >= 3:
                        now = time.time()
                        if self.last_good_gps:
                            self.gps_dts.append(now - self.last_good_gps)
                        self.last_good_gps = now
                elif t == "STATUSTEXT":
                    text = self._chunk + msg.text
                    if len(msg.text) >= 50:
                        self._chunk = text
                        continue
                    self._chunk = ""
                    if any(k in text for k in ("ailsafe", "Takeoff", "Landing", "Disarm", "lost")):
                        LOG.append(f"{time.time() - T0:5.0f}s  {self.name} PX4: {text.strip()[:60]}")

    # ---- commands ----
    def cmd(self, c, *p):
        p = list(p) + [0] * (7 - len(p))
        self.m.mav.command_long_send(self.sysid, 1, c, 0, *p)

    def param(self, name, value, is_int=True):
        if is_int:
            value = struct.unpack("<f", struct.pack("<i", int(value)))[0]
            t = mavutil.mavlink.MAV_PARAM_TYPE_INT32
        else:
            t = mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        self.m.mav.param_set_send(self.sysid, 1, name.encode(), value, t)

    def mode_set(self, main, sub_=0):
        self.cmd(mavutil.mavlink.MAV_CMD_DO_SET_MODE, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, main, sub_)

    def setup(self):
        for name, v, is_int in [("NAV_DLL_ACT", 0, True), ("COM_RC_IN_MODE", 1, True), ("SYS_FAILURE_EN", 1, True),
                                ("MIS_TAKEOFF_ALT", CRUISE_ALT, False), ("MPC_XY_CRUISE", 7.0, False),
                                ("RTL_RETURN_ALT", CRUISE_ALT + 3, False)]:
            self.param(name, v, is_int)

    def takeoff(self):
        self.takeoff_tries += 1
        self.takeoff_at = time.time()
        self.mode_set(4, 2)
        time.sleep(0.15)
        self.cmd(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)

    def goto(self, p, alt=CRUISE_ALT):
        lat, lon = Ref.latlon(*p)
        self.m.mav.command_int_send(self.sysid, 1, mavutil.mavlink.MAV_FRAME_GLOBAL,
                                    mavutil.mavlink.MAV_CMD_DO_REPOSITION, 0, 0, -1,
                                    mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, 0, float("nan"),
                                    int(lat * 1e7), int(lon * 1e7), Ref.alt + alt)

    def gps_fail(self, off):
        self.cmd(mavutil.mavlink.MAV_CMD_INJECT_FAILURE, mavutil.mavlink.FAILURE_UNIT_SENSOR_GPS,
                 mavutil.mavlink.FAILURE_TYPE_OFF if off else mavutil.mavlink.FAILURE_TYPE_OK, 0)

    def heartbeat_and_sticks(self):
        self.m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        if self.connected:
            x, y, z, r = self.sticks
            self.m.mav.manual_control_send(self.sysid, x, y, z, r, 0)


class GazeboCamera:
    """Gazebo window camera follows a model (`gz service` in WSL, background thread)."""

    def __init__(self):
        self.view, self.target = "5", 0          # overview of drone 1
        self.pending, self.last_sent, self.wake = None, None, threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def _gz(service, reqtype, req):
        try:
            r = subprocess.run(["wsl.exe", "-e", "env", "GZ_IP=127.0.0.1", "gz", "service", "-s", service,
                                "--reqtype", reqtype, "--reptype", "gz.msgs.Boolean", "--timeout", "3000",
                                "--req", req], capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "true" in r.stdout
        except Exception:
            return False

    def _worker(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            job, self.pending = self.pending, None
            if job:
                model, off = job
                self._gz("/gui/follow", "gz.msgs.StringMsg", f'data: "{model}"')
                self._gz("/gui/follow/offset", "gz.msgs.Vector3d", f"x: {off[0]:.1f}, y: {off[1]:.1f}, z: {off[2]:.1f}")
                self.last_sent = job

    def offset(self, yaw):
        # Gazebo offsets are world-frame: x East, y North, z up
        return {"1": (-9 * math.sin(yaw), -9 * math.cos(yaw), 3.5), "2": (-3.0, -3.0, 2.5), "3": (0.1, 0.0, 45.0),
                "4": (0.0, -18.0, 4.0), "5": (-35.0, -35.0, 28.0)}[self.view]

    def show(self, view=None, target=None, yaw=0.0):
        self.view = view or self.view
        self.target = self.target if target is None else target
        model = "target_facility" if self.target == "target" else GZ_MODELS[self.target]
        off = (-45.0, -45.0, 35.0) if self.target == "target" else self.offset(yaw)
        self.pending = (model, off)
        self.wake.set()

    def tick(self, yaw):
        if self.view == "1" and self.target != "target" and self.last_sent and self.pending is None:
            want = self.offset(yaw)
            if dist(want, self.last_sent[1]) > 2.5:
                self.pending = (GZ_MODELS[self.target], want)
                self.wake.set()


def add_nogo(c, r, who):
    """Add a danger zone; zones that overlap are merged into one enclosing circle (keeps routes simple)."""
    zones = S["nogos"] + [(c, r, who)]
    merged = True
    while merged and len(zones) > 1:
        merged = False
        for a in range(len(zones)):
            for b in range(a + 1, len(zones)):
                (c1, r1, w1), (c2, r2, w2) = zones[a], zones[b]
                dd = dist(c1, c2)
                if dd < r1 + r2:
                    if dd + r2 <= r1:
                        new = (c1, r1, w1)
                    elif dd + r1 <= r2:
                        new = (c2, r2, w2)
                    else:
                        R = (dd + r1 + r2) / 2
                        k = (R - r1) / dd
                        new = ((c1[0] + (c2[0] - c1[0]) * k, c1[1] + (c2[1] - c1[1]) * k), R, w1 + "+" + w2)
                    zones = [z for i, z in enumerate(zones) if i not in (a, b)] + [new]
                    merged = True
                    break
            if merged:
                break
    S["nogos"] = zones


def route(start, goal, nogos):
    """Waypoints from start to goal that go around every no-go circle the straight line crosses."""
    wps, cur = [], start
    for c, r, *_ in nogos:
        if dist(cur, c) < r:      # already inside the danger zone: first get out, straight away from its centre
            out = unit(sub(cur, c))
            cur = (c[0] + (r + 12) * out[0], c[1] + (r + 12) * out[1])
            wps.append(cur)
        d = sub(goal, cur)
        L = math.hypot(*d) or 1.0
        u = (d[0] / L, d[1] / L)
        w = sub(c, cur)
        t = max(0.0, min(L, w[0] * u[0] + w[1] * u[1]))
        closest = (cur[0] + u[0] * t, cur[1] + u[1] * t)
        if dist(closest, c) >= r:
            continue
        # (if the goal itself is inside this conservative circle we still go around and come in
        #  from the goal's side - the last leg is radial, away from the circle's centre)
        # walk around the circle on the side the line passes, radius r + 12 (live drones overshoot turns)
        R = r + 12.0
        a0 = math.atan2(cur[1] - c[1], cur[0] - c[0])
        a1 = math.atan2(goal[1] - c[1], goal[0] - c[0])
        sweep = (a1 - a0) % (2 * math.pi)          # counter-clockwise
        if sweep > math.pi:                          # the other way round is shorter
            sweep -= 2 * math.pi
        n = max(2, int(abs(sweep) / math.radians(35)))
        for k in range(1, n):
            a = a0 + sweep * k / n
            wps.append((c[0] + R * math.cos(a), c[1] + R * math.sin(a)))
        cur = wps[-1]
    wps.append(goal)
    return wps


# ---------------- state ----------------
drones = [Drone(i) for i in range(N_DRONES)]
camera = GazeboCamera()
S = {"sharing": True, "nogos": [], "mission_t": None, "keys": set(), "events_done": set()}


def tx_loop():
    while True:
        for d in drones:
            d.heartbeat_and_sticks()
        time.sleep(0.05)


threading.Thread(target=tx_loop, daemon=True).start()


def set_task(d, task, wps=None):
    d.task, d.wps, d.sent_wp = task, list(wps or []), None


def plan_for(d, goal):
    return route(d.pos, goal, S["nogos"] if S["sharing"] else [n for n in S["nogos"] if d.name in n[2]])


def act(a):
    if a == "quit":
        plt.close("all")
    elif a == "mission":
        if Ref.lat is None or not all(d.offset for d in drones):
            if not S.get("mission_pending"):
                log("> mission queued - starts as soon as all drones are ready")
            S["mission_pending"] = True
            return
        S["mission_pending"] = False
        S["mission_t"] = time.time()
        for d in drones:
            d.launch_at = S["mission_t"] + d.i * LAUNCH_GAP
            set_task(d, "waiting")
        log(f"> MISSION: {N_DRONES} drones to the target, scout first, {LAUNCH_GAP:.0f} s apart")
    elif a == "home":
        for d in drones:
            if d.armed and d.task != "escape":
                set_task(d, "home", plan_for(d, PADS[d.i]))
        log("> all drones: home to the base")
    elif a == "land":
        for d in drones:
            set_task(d, "idle")
            d.mode_set(4, 6)
        log("> all drones: land where you are")
    elif a == "sharing":
        S["sharing"] = not S["sharing"]
        log(f"> swarm sharing {'ON' if S['sharing'] else 'OFF (each drone on its own)'}")
    elif a == "takeoff1":
        drones[0].takeoff()
        set_task(drones[0], "manual")
        log("> D1 take off (manual)")
    elif a == "jam1":
        d = drones[0]
        d.jam_on = not d.jam_on
        d.gps_fail(d.jam_on)
        log(f"> D1 GPS {'JAMMED (manual)' if d.jam_on else 'restored'}")
    elif a == "camnext":
        t = camera.target if camera.target != "target" else -1
        act_cam(target=(t + 1) % N_DRONES)
    elif a == "camtarget":
        camera.show(target="target")
        log("> camera on the target")
    elif a in CAMERA_VIEWS:
        act_cam(view=a)


def act_cam(view=None, target=None):
    tgt = camera.target if target is None else target
    tgt = 0 if tgt == "target" else tgt
    camera.show(view=view, target=tgt, yaw=drones[tgt].yaw)
    log(f"> camera: {CAMERA_VIEWS[camera.view]} on {drones[tgt].name}")


KEY_ACTIONS = {"escape": "quit", "m": "mission", "h": "home", "l": "land", "n": "sharing", "t": "takeoff1",
               "j": "jam1", "tab": "camnext", "6": "camtarget", **{k: k for k in CAMERA_VIEWS}}
MOVE_KEYS = {"up", "down", "left", "right", "w", "a", "s", "d", "r", "f", "q", "e"}


def on_press(ev):
    k = (ev.key or "").lower()
    S["keys"].add(k)
    if k in KEY_ACTIONS:
        act(KEY_ACTIONS[k])
    elif k in MOVE_KEYS and drones[0].armed:
        if drones[0].task != "manual":
            set_task(drones[0], "manual")
            drones[0].mode_set(3)
            log("> D1 manual control")


def on_release(ev):
    S["keys"].discard((ev.key or "").lower())


def body_sticks(d, north, east, scale=STICK):
    c, s = math.cos(d.yaw), math.sin(d.yaw)
    return int(scale * (north * c + east * s)), int(scale * (-north * s + east * c))


# ---------------- the brain: runs 10x per second ----------------
def step():
    now = time.time()
    keys = S["keys"]
    if S.get("mission_pending") and Ref.lat is not None and all(d.offset for d in drones):
        act("mission")
    for d in drones:
        if d.connected and not d.setup_done:
            d.setup()
            d.setup_done = True
            log(f"{d.name} connected")
            if d.i == 0:
                camera.show(view="5", target=0)
        p = d.pos
        gps = d.gps_ok(now)

        # --- scene: the jammer cuts GPS inside the red dome (the drone is not told) ---
        inside = math.hypot(dist(p, JAMMER), d.alt) < JAM_RADIUS
        if d.armed and inside and not d.jam_on:
            d.jam_on = True
            d.gps_fail(True)
        elif d.jam_on and not inside and d.task == "escape":
            d.jam_on = False
            d.gps_fail(False)

        # --- breadcrumbs + tracks ---
        if d.armed:
            (d.track if gps else d.blind_track)[0].append(p[1]); (d.track if gps else d.blind_track)[1].append(p[0])
            other = d.blind_track if gps else d.track
            if other[0] and not math.isnan(other[0][-1]):
                other[0].append(math.nan); other[1].append(math.nan)
            if gps and d.alt > 2 and (not d.crumbs or dist(p, d.crumbs[-1]) > 4):
                d.crumbs.append(p)

        # --- DETECT: our monitor ---
        if d.armed and d.alt > 2.0 and not gps and not d.alarm and d.last_good_gps:
            d.alarm = True
            log(f"{d.name}: GPS LOST -> our monitor alarm after {now - d.last_good_gps:.1f} s")
            loss = d.crumbs[-1] if d.crumbs else p
            heading = unit(sub(loss, d.crumbs[-4])) if len(d.crumbs) >= 4 else unit(sub(OBS[d.i], loss))
            centre = (loss[0] + NOGO_AHEAD * heading[0], loss[1] + NOGO_AHEAD * heading[1])
            add_nogo(centre, NOGO_RADIUS, d.name)
            if S["sharing"]:
                log(f"{d.name}: BROADCAST danger zone (r {NOGO_RADIUS:.0f} m, ahead of where GPS died)")
            if d.task in ("enroute", "climb", "home", "observe"):
                # ESCAPE blind: back along own breadcrumbs, IMU only (Altitude mode needs no GPS)
                back = [c for c in reversed(d.crumbs) if dist(c, loss) >= ESCAPE_BACK]
                d.escape_to = back[0] if back else PADS[d.i]
                d.escape_until = now + 25
                d.resume_goal = d.wps[-1] if d.wps else OBS[d.i]
                set_task(d, "escape")
                d.mode_set(2)
                log(f"{d.name}: blind escape along own breadcrumbs ({ESCAPE_BACK:.0f} m back)")
            # everyone else reroutes around what we just learned
            for o in drones:
                if o is not d and o.task in ("enroute", "climb", "waiting", "home") and S["sharing"]:
                    goal = o.wps[-1] if o.wps else OBS[o.i]
                    if o.task == "enroute":
                        old = len(o.wps)
                        set_task(o, "enroute", plan_for(o, goal))
                        if len(o.wps) > 1 or old > 1:
                            log(f"{o.name}: rerouted around the danger zone, stays on GPS")
        if gps and d.alarm and d.task != "escape":
            d.alarm = False

        # --- tasks ---
        sticks = (0, 0, 500, 0)
        if d.task == "waiting" and d.launch_at and now >= d.launch_at:
            d.takeoff_tries = 0
            d.takeoff()
            set_task(d, "climb")
            log(f"{d.name}: take off")
        elif d.task == "climb" and not d.armed and now - d.takeoff_at > 3 and d.takeoff_tries < 15:
            d.takeoff()             # PX4 refuses to arm until its preflight checks pass: try again
        elif d.task == "climb" and d.armed and d.alt > CRUISE_ALT - 2:
            set_task(d, "enroute", plan_for(d, OBS[d.i]))
        elif d.task in ("enroute", "home") and d.wps:
            wp = d.wps[0]
            # (re)send: PX4 rejects "go to" for a few seconds after GPS comes back, so repeat until it flies
            if d.sent_wp != wp or (d.mode not in ("HOLD", "MISSION") and now - d.sent_at > 2.5):
                d.goto(wp)
                d.sent_wp, d.sent_at = wp, now
            if dist(p, wp) < 4.0:
                d.wps.pop(0)
                if not d.wps:
                    if d.task == "home":
                        d.mode_set(4, 6)
                        set_task(d, "idle")
                        log(f"{d.name}: over its pad - landing")
                    else:
                        set_task(d, "observe")
                        log(f"{d.name}: ON STATION at the target ({dist(p, TARGET):.0f} m stand-off)")
        elif d.task == "escape":
            to = sub(d.escape_to, p)
            if math.hypot(*to) > 3 and now < d.escape_until:
                v_des = unit(to)
                v_err = (4.0 * v_des[0] - d.vn, 4.0 * v_des[1] - d.ve)
                sn, se = max(-1, min(1, 0.25 * v_err[0])), max(-1, min(1, 0.25 * v_err[1]))
                pitch, roll = body_sticks(d, sn, se, 650)
                sticks = (pitch, roll, 500, 0)
            if gps:
                d.gps_back_at = d.gps_back_at or now
                if now - d.gps_back_at > 2.5:
                    d.gps_back_at = None
                    d.alarm = False
                    set_task(d, "enroute", plan_for(d, d.resume_goal))
                    log(f"{d.name}: GPS back - new route around the danger zone")
        elif d.task == "manual" and d.i == 0:
            north = ("up" in keys or "w" in keys) - ("down" in keys or "s" in keys)
            east = ("right" in keys or "d" in keys) - ("left" in keys or "a" in keys)
            pitch, roll = body_sticks(d, north, east)
            sticks = (pitch, roll, 500 + 300 * (("r" in keys) - ("f" in keys)), 400 * (("e" in keys) - ("q" in keys)))
        d.sticks = sticks
    camera.tick(drones[camera.target].yaw if camera.target != "target" else 0.0)


# ---------------- window ----------------
fig = plt.figure(figsize=(15.5, 9.4))
fig.canvas.manager.set_window_title("Swarm mission - GNSS-denied demo")
gs = fig.add_gridspec(1, 2, width_ratios=[1.6, 1], wspace=0.04, bottom=0.17, top=0.92)
ax = fig.add_subplot(gs[0])
panel = fig.add_subplot(gs[1]); panel.axis("off")
fig.suptitle("Live swarm mission  |  DETECT → ESCAPE → SHARE → REROUTE", fontsize=15, weight="bold")

ax.set_xlim(-25, 130); ax.set_ylim(-60, 50); ax.set_aspect("equal"); ax.grid(alpha=0.2)
ax.set_xlabel("East [m]"); ax.set_ylabel("North [m]")
ax.set_title("Map — where each drone believes it is", fontsize=11)
ax.add_patch(Rectangle((-22, -14), 20, 28, color="#1a9e3f", alpha=0.10))
ax.text(-12, -17, "BASE", ha="center", va="top", color="#1a7f37", weight="bold")
for i in range(N_DRONES):
    ax.add_patch(Rectangle((PADS[i][1] - 2, PADS[i][0] - 2), 4, 4, color="#1a9e3f", alpha=0.35))
ax.add_patch(Circle((JAMMER[1], JAMMER[0]), JAM_RADIUS, color="#cf222e", alpha=0.10, ls="--"))
ax.text(JAMMER[1], JAMMER[0] - JAM_RADIUS - 3, "jammer (unknown to drones)", ha="center", va="top",
        color="#cf222e", fontsize=8)
ax.add_patch(Rectangle((TARGET[1] - 9, TARGET[0] - 9), 18, 18, color="#6e4b00", alpha=0.6))
ax.text(TARGET[1], TARGET[0] + 12, "TARGET", ha="center", color="#6e4b00", weight="bold")
for i, o in enumerate(OBS[:N_DRONES]):
    ax.plot(o[1], o[0], "x", color=COLORS[i], ms=9, mew=2)
nogo_artists = []
tracks = [ax.plot([], [], color=d.color, lw=2)[0] for d in drones]
blinds = [ax.plot([], [], color="#cf222e", lw=2.5, ls=":")[0] for d in drones]
dots = [ax.plot([], [], marker=(3, 0, 0), ms=15, color=d.color, mec="black")[0] for d in drones]
labels = [ax.text(0, 0, d.name, fontsize=9, weight="bold", color=d.color) for d in drones]
ax.plot([], [], color="#e8710a", lw=2, label="Shared danger zone (no-go)")
ax.plot([], [], color="#cf222e", lw=2.5, ls=":", label="Flying without GPS")
ax.plot([], [], "x", color="black", label="Observation point (stand-off)")
ax.legend(loc="upper left", fontsize=8)

banner = FancyBboxPatch((0.02, 0.86), 0.96, 0.12, boxstyle="round,pad=0.01", transform=panel.transAxes, color="#1a9e3f")
panel.add_patch(banner)
banner_txt = panel.text(0.5, 0.92, "", transform=panel.transAxes, ha="center", va="center", fontsize=15,
                        weight="bold", color="white")
status_txt = panel.text(0.02, 0.83, "", transform=panel.transAxes, va="top", family="monospace", fontsize=9.5)
log_txt = panel.text(0.02, 0.55, "", transform=panel.transAxes, va="top", family="monospace", fontsize=8.2,
                     color="#333333")

BUTTONS = [("START MISSION (M)", "mission", "#c8f0d0"), ("Sharing ON/OFF (N)", "sharing", "#fff2c2"),
           ("All home (H)", "home", "#dbe9ff"), ("Land all (L)", "land", "#dbe9ff"),
           ("D1 take off (T)", "takeoff1", "#eeeeee"), ("D1 jam GPS (J)", "jam1", "#ffd6d6"),
           ("Quit (Esc)", "quit", "#eeeeee")]
CAMS = [("Cam: chase (1)", "1"), ("Cam: close (2)", "2"), ("Cam: top (3)", "3"), ("Cam: side (4)", "4"),
        ("Cam: overview (5)", "5"), ("Cam: next drone (Tab)", "camnext"), ("Cam: target (6)", "camtarget")]
_btn = []
for row, items in ((0.08, BUTTONS), (0.025, CAMS)):
    for k, item in enumerate(items):
        label, action = item[0], item[1]
        colour = item[2] if len(item) > 2 else "#e9f5ec"
        b = Button(fig.add_axes((0.015 + k * 0.139, row, 0.134, 0.045)), label, color=colour, hovercolor="#bcd4ff")
        b.label.set_fontsize(9)
        b.on_clicked(lambda _e, a=action: act(a))
        _btn.append(b)


def draw(_):
    step()
    now = time.time()
    for a in nogo_artists:
        a.remove()
    nogo_artists.clear()
    for c, r, who in S["nogos"]:
        nogo_artists.append(ax.add_patch(Circle((c[1], c[0]), r, fill=False, ec="#e8710a", lw=2,
                                                ls="-" if S["sharing"] else ":")))
    lines = []
    any_jam = [d for d in drones if d.armed and not d.gps_ok(now)]
    for d, tr, bl, dot, lab in zip(drones, tracks, blinds, dots, labels):
        tr.set_data(*d.track); bl.set_data(*d.blind_track)
        p = d.pos
        dot.set_data([p[1]], [p[0]]); dot.set_marker((3, 0, -math.degrees(d.yaw)))
        lab.set_position((p[1] + 2.5, p[0] + 2.5))
        gps = "GPS ok " if d.gps_ok(now) else "NO GPS "
        lines.append(f"{d.name} {gps} {d.mode[:9]:9s} {d.task:8s} alt {d.alt:4.1f}  to target {dist(p, TARGET):5.0f} m")
    on_station = sum(d.task == "observe" for d in drones)
    if not any(d.connected for d in drones):
        banner.set_color("#888888"); banner_txt.set_text("WAITING FOR SIMULATOR…")
    elif any_jam:
        banner.set_color("#cf222e"); banner_txt.set_text(f"GPS JAMMED: {', '.join(d.name for d in any_jam)}")
    elif on_station:
        banner.set_color("#1a7f37"); banner_txt.set_text(f"ON STATION: {on_station}/{N_DRONES} at the target")
    else:
        banner.set_color("#1a9e3f"); banner_txt.set_text("ALL GPS TRUSTED")
    lines.append(f"\nSwarm sharing: {'ON' if S['sharing'] else 'OFF'}    danger zones known: {len(S['nogos'])}")
    status_txt.set_text("\n".join(lines))
    with LOCK:
        log_txt.set_text("Events\n" + "\n".join(LOG))
    return []


if __name__ == "__main__":
    fig.canvas.mpl_connect("key_press_event", on_press)
    fig.canvas.mpl_connect("key_release_event", on_release)
    anim = FuncAnimation(fig, draw, interval=100, cache_frame_data=False)
    plt.show()
