"""Live demo: fly the PX4 SITL drone with the keyboard and jam its GPS.

Shows a top-down map (START, point B, PX4's estimated track, GPS fixes,
breadcrumbs recorded while GPS is trusted) and a status panel with
our GPS monitor vs PX4's own reaction time.

Start the simulator first (inside Ubuntu):
    cd ~/PX4-Autopilot && PX4_GZ_WORLD=demo make px4_sitl gz_x500
Then on Windows:
    py demo_control.py

Everything also has a button (click with the mouse). Keys work when the
app window has focus (click it once):
    W A S D / arrows   fly North / West / South / East (map directions; takes manual control)
    R / F              climb / descend          Q / E   rotate left / right
    T  take off (5 m)          B  fly to point B         H  fly home to START and land
    L  land here               G  jam GPS on/off         X  motors off (emergency)
    1-5  Gazebo camera: chase, close, top, side, overview
    C  clear track             Esc  quit
"""
import subprocess
import math
import os
import struct
import threading
import time
from collections import deque

import matplotlib

matplotlib.use("Agg" if os.environ.get("DEMO_HEADLESS") else "TkAgg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import FancyBboxPatch
from pymavlink import mavutil

# ---------------- SETTINGS ----------------
CONNECTION = "udpin:0.0.0.0:14550"   # PX4 SITL GCS link (needs WSL mirrored networking)
B_NORTH, B_EAST = 20.0, 25.0         # point B in metres from START (matches sim/demo.sdf)
TAKEOFF_ALT = 5.0                    # m
CRUISE_ALT = 5.0                     # m above home, used for "fly to B"
STICK = 500                          # manual stick deflection (of 1000) for arrow keys
GPS_SILENT_LIMIT = 1.0               # s without a good GPS fix -> our monitor raises the alarm
BREADCRUMB_SPACING = 3.0             # m between breadcrumbs while GPS is trusted
GZ_MODEL = "x500_0"                  # drone name in Gazebo
CAMERA_VIEWS = {                     # follow offsets from the drone, metres (Gazebo: x East, y North, z up)
    "1": ("Chase (behind)", None),   # computed from heading
    "2": ("Close", (-2.0, -2.0, 2.0)),
    "3": ("Top-down", (0.1, 0.0, 35.0)),
    "4": ("Side", (0.0, -14.0, 3.0)),
    "5": ("Overview", (-28.0, -28.0, 22.0)),
}
MAP_EAST = (-12, 42)
MAP_NORTH = (-12, 34)
# -------------------------------------------

for key in [k for k in plt.rcParams if k.startswith("keymap.")]:
    plt.rcParams[key] = []           # free all keys from matplotlib shortcuts

PX4_MAIN = {1: "MANUAL", 2: "ALTITUDE", 3: "POSITION", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED"}
PX4_AUTO = {1: "READY", 2: "TAKEOFF", 3: "HOLD", 4: "MISSION", 5: "RETURN", 6: "LAND", 9: "PRECLAND",
            20: "BLIND DESCENT (no position)"}   # sub-modes from PX4 px4_custom_mode.h

GREEN, RED, ORANGE, BLUE, GOLD, GREY = "#1a9e3f", "#d62728", "#f28e2b", "#2a6fdb", "#c9a227", "#888888"


class Drone:
    """MAVLink link + latest vehicle state (updated by a background thread)."""

    def __init__(self):
        self.m = mavutil.mavlink_connection(CONNECTION, source_system=255, source_component=190)
        self.lock = threading.Lock()
        self.connected = False
        self.armed = False
        self.mode = "?"
        self.n = self.e = self.alt = self.speed = 0.0
        self.pos_valid = False
        self.yaw = 0.0
        self.home = None                  # (lat, lon, alt_m) of START, locked at first contact
        # PX4 moves its own "home" to wherever the drone is armed; we keep START fixed
        self.gps_fix = 0
        self.gps_sats = 0
        self.gps_ne = None
        self.last_good_gps = None
        self.gps_dts = deque(maxlen=20)
        self.events = deque(maxlen=7)
        self._chunk = ""
        self.t0 = time.time()
        self.sticks = (0, 0, 500, 0)      # pitch(N in body), roll, throttle, yaw
        self.running = True
        threading.Thread(target=self._rx, daemon=True).start()
        threading.Thread(target=self._tx, daemon=True).start()

    # ---- helpers ----
    def log(self, text):
        with self.lock:
            self.events.append(f"{time.time() - self.t0:6.1f}s  {text}")

    def _ned_from_latlon(self, lat, lon):
        lat0, lon0, _ = self.home
        r = 6378137.0
        return (math.radians(lat - lat0) * r,
                math.radians(lon - lon0) * r * math.cos(math.radians(lat0)))

    def latlon_from_ned(self, n, e):
        lat0, lon0, _ = self.home
        r = 6378137.0
        return (lat0 + math.degrees(n / r),
                lon0 + math.degrees(e / (r * math.cos(math.radians(lat0)))))

    # ---- threads ----
    def _rx(self):
        while self.running:
            msg = self.m.recv_match(blocking=True, timeout=0.5)
            if msg is None:
                continue
            t = msg.get_type()
            with self.lock:
                if t == "HEARTBEAT" and msg.get_srcSystem() == 1 and msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_PX4:
                    if not self.connected:
                        self.connected = True
                        self.events.append(f"{time.time() - self.t0:6.1f}s  connected to PX4")
                    self.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                    main = (msg.custom_mode >> 16) & 0xFF
                    sub = (msg.custom_mode >> 24) & 0xFF
                    self.mode = PX4_AUTO.get(sub, f"AUTO-{sub}") if main == 4 else PX4_MAIN.get(main, str(main))
                elif t == "LOCAL_POSITION_NED":
                    self.n, self.e, self.alt = msg.x, msg.y, -msg.z
                    self.speed = math.hypot(msg.vx, msg.vy)
                    self.pos_valid = True
                elif t == "ATTITUDE":
                    self.yaw = msg.yaw
                elif t == "HOME_POSITION" and self.home is None:
                    self.home = (msg.latitude / 1e7, msg.longitude / 1e7, msg.altitude / 1000.0)
                elif t == "GPS_RAW_INT":
                    self.gps_fix, self.gps_sats = msg.fix_type, msg.satellites_visible
                    if msg.fix_type >= 3:
                        now = time.time()
                        if self.last_good_gps:
                            self.gps_dts.append(now - self.last_good_gps)
                        self.last_good_gps = now
                        if self.home:
                            self.gps_ne = self._ned_from_latlon(msg.lat / 1e7, msg.lon / 1e7)
                elif t == "STATUSTEXT":
                    # Long PX4 messages arrive in 50-char chunks: glue them back together
                    text = self._chunk + msg.text
                    if len(msg.text) >= 50:
                        self._chunk = text
                        continue
                    self._chunk = ""
                    self.events.append(f"{time.time() - self.t0:6.1f}s  PX4: {text.strip()}")
                    if "ailsafe" in text:
                        self.last_failsafe = time.time()
                elif t == "COMMAND_ACK" and msg.result != 0:
                    name = mavutil.mavlink.enums["MAV_CMD"].get(msg.command)
                    res = mavutil.mavlink.enums["MAV_RESULT"].get(msg.result)
                    self.events.append(f"{time.time() - self.t0:6.1f}s  REJECTED {name.name if name else msg.command}: "
                                       f"{res.name.replace('MAV_RESULT_', '') if res else msg.result}")

    def _tx(self):
        last_hb = 0
        while self.running:
            now = time.time()
            if now - last_hb > 1.0:
                self.m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                last_hb = now
            if self.connected:
                x, y, z, r = self.sticks
                self.m.mav.manual_control_send(1, x, y, z, r, 0)
            time.sleep(0.05)

    # ---- commands ----
    def command(self, cmd, *params):
        p = list(params) + [0] * (7 - len(params))
        self.m.mav.command_long_send(1, 1, cmd, 0, *p)

    def set_param(self, name, value, is_int=True):
        if is_int:  # PX4 uses bytewise encoding for integer params
            value = struct.unpack("<f", struct.pack("<i", int(value)))[0]
            ptype = mavutil.mavlink.MAV_PARAM_TYPE_INT32
        else:
            ptype = mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        self.m.mav.param_set_send(1, 1, name.encode(), value, ptype)

    def set_mode(self, main, sub=0):
        self.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE,
                     mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, main, sub)

    def setup(self):
        self.set_param("NAV_DLL_ACT", 0)          # no "GCS lost" failsafe
        self.set_param("COM_RC_IN_MODE", 1)       # accept MAVLink joystick (this app)
        self.set_param("SYS_FAILURE_EN", 1)       # allow GPS failure injection
        self.set_param("MIS_TAKEOFF_ALT", TAKEOFF_ALT, is_int=False)
        self.set_param("RTL_RETURN_ALT", CRUISE_ALT + 3, is_int=False)  # default 60 m is too high for the demo
        self.set_param("RTL_DESCEND_ALT", CRUISE_ALT, is_int=False)

    def takeoff(self):
        self.set_mode(4, 2)
        time.sleep(0.2)
        self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)

    def goto(self, n, e):
        if not self.home:
            self.log("no home position yet")
            return
        lat, lon = self.latlon_from_ned(n, e)
        self.m.mav.command_int_send(
            1, 1, mavutil.mavlink.MAV_FRAME_GLOBAL, mavutil.mavlink.MAV_CMD_DO_REPOSITION, 0, 0,
            -1, mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, 0, float("nan"),
            int(lat * 1e7), int(lon * 1e7), self.home[2] + CRUISE_ALT)

    def gps(self, on):
        self.command(mavutil.mavlink.MAV_CMD_INJECT_FAILURE,
                     mavutil.mavlink.FAILURE_UNIT_SENSOR_GPS,
                     mavutil.mavlink.FAILURE_TYPE_OK if on else mavutil.mavlink.FAILURE_TYPE_OFF, 0)


class GazeboCamera:
    """Moves the Gazebo window's camera (it follows the drone) via `gz service` inside WSL.
    Calls run in a background thread so the app never freezes; only the newest request is sent."""

    def __init__(self):
        self.view = "2"
        self.pending = None
        self.last_sent = None
        self.ok = None              # None = not tried yet, True/False = last call worked
        self.wake = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    def _gz(self, service, reqtype, req):
        cmd = ["wsl.exe", "-e", "env", "GZ_IP=127.0.0.1", "gz", "service", "-s", service,
               "--reqtype", reqtype, "--reptype", "gz.msgs.Boolean", "--timeout", "3000", "--req", req]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "true" in r.stdout
        except Exception:
            return False

    def _worker(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            offset, self.pending = self.pending, None
            if offset is None:
                continue
            self._gz("/gui/follow", "gz.msgs.StringMsg", f'data: "{GZ_MODEL}"')
            self.ok = self._gz("/gui/follow/offset", "gz.msgs.Vector3d",
                               f"x: {offset[0]:.1f}, y: {offset[1]:.1f}, z: {offset[2]:.1f}")
            self.last_sent = offset

    def chase_offset(self, yaw):
        # 8 m behind and 3 m above the drone; PX4 yaw is from North, clockwise -> Gazebo x=East, y=North
        return (-8.0 * math.sin(yaw), -8.0 * math.cos(yaw), 3.0)

    def set_view(self, key, yaw=0.0):
        self.view = key
        offset = CAMERA_VIEWS[key][1] or self.chase_offset(yaw)
        self.pending = offset
        self.wake.set()

    def tick(self, yaw):
        """Chase view: re-aim behind the drone when it has turned."""
        if self.view != "1" or self.last_sent is None or self.pending is not None:
            return
        want = self.chase_offset(yaw)
        if math.hypot(want[0] - self.last_sent[0], want[1] - self.last_sent[1]) > 2.0:   # ~15 degrees
            self.pending = want
            self.wake.set()


drone = Drone()
camera = GazeboCamera()
keys = set()
state = {"jam_t": None, "monitor_t": None, "px4_t": None, "jammed": False,
         "track_ok": ([], []), "track_bad": ([], []), "gps_pts": ([], []), "crumbs": ([], []),
         "setup_done": False, "prev_gps_ok": True, "homing": False}
drone.last_failsafe = None

MOVE_KEYS = {"up", "down", "left", "right", "w", "a", "s", "d", "r", "f", "q", "e", "pageup", "pagedown"}
MANUAL_MODES = ("POSITION", "ALTITUDE", "MANUAL", "STABILIZED")


def act(action):
    """Every action is reachable from a key and from a button."""
    if action == "quit":
        drone.running = False
        plt.close("all")
    elif action == "takeoff":
        drone.log("> take off")
        drone.takeoff()
    elif action == "b":
        state["homing"] = False
        drone.log("> fly to point B")
        drone.goto(B_NORTH, B_EAST)
    elif action == "home":
        drone.log("> fly home to START, then land")
        state["homing"] = True
        drone.goto(0.0, 0.0)          # START is locked at first contact, not PX4's moving "home"
    elif action == "land":
        state["homing"] = False
        drone.log("> land here")
        drone.set_mode(4, 6)
    elif action == "disarm":
        state["homing"] = False
        drone.log("> motors off")
        drone.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 21196)
    elif action == "jam":
        state["jammed"] = not state["jammed"]
        drone.gps(on=not state["jammed"])
        if state["jammed"]:
            drone.log("> GPS JAMMING STARTED")
            state.update(jam_t=time.time(), monitor_t=None, px4_t=None)
            drone.last_failsafe = None
        else:
            drone.log("> GPS jamming stopped")
    elif action == "clear":
        for v in ("track_ok", "track_bad", "gps_pts", "crumbs"):
            state[v] = ([], [])
    elif action in CAMERA_VIEWS:
        drone.log(f"> camera: {CAMERA_VIEWS[action][0]}")
        camera.set_view(action, drone.yaw)


KEY_ACTIONS = {"escape": "quit", "t": "takeoff", "b": "b", "h": "home", "l": "land", "x": "disarm",
               "g": "jam", "c": "clear", **{k: k for k in CAMERA_VIEWS}}


def on_press(ev):
    k = (ev.key or "").lower()
    keys.add(k)
    if k in KEY_ACTIONS:
        act(KEY_ACTIONS[k])
    elif k in MOVE_KEYS:
        state["homing"] = False
        if drone.mode not in MANUAL_MODES:
            drone.set_mode(3)   # pilot takes over: Position mode (PX4 falls back to Altitude without GPS)


def on_release(ev):
    keys.discard((ev.key or "").lower())


def held(*names):
    return any(n in keys for n in names)


def update_sticks():
    north = held("up", "w") - held("down", "s")
    east = held("right", "d") - held("left", "a")
    # Keys are map directions; sticks are in the drone's body frame -> rotate by yaw
    c, s = math.cos(drone.yaw), math.sin(drone.yaw)
    pitch = STICK * (north * c + east * s)
    roll = STICK * (-north * s + east * c)
    throttle = 500 + 300 * (held("r", "pageup") - held("f", "pagedown"))
    yaw = 400 * (held("e") - held("q"))
    drone.sticks = (int(pitch), int(roll), int(throttle), int(yaw))


# ---------------- figure ----------------
fig = plt.figure(figsize=(15, 9.2))
fig.canvas.manager.set_window_title("GNSS-denied demo")
gs = fig.add_gridspec(1, 2, width_ratios=[1.55, 1], wspace=0.05, bottom=0.17, top=0.92)
ax = fig.add_subplot(gs[0])
panel = fig.add_subplot(gs[1])
panel.axis("off")
fig.suptitle("Live PX4 drone  |  GPS can be jammed  |  DETECT → NAVIGATE → LOCATE → SHARE → REROUTE",
             fontsize=14, weight="bold")

# Buttons (mouse) - same actions as the keys
from matplotlib.widgets import Button  # noqa: E402

BUTTONS = [  # (label, action, colour)
    ("Take off (T)", "takeoff", "#dbe9ff"), ("Fly to B (B)", "b", "#dbe9ff"),
    ("Home to START (H)", "home", "#dbe9ff"), ("Land (L)", "land", "#dbe9ff"),
    ("JAM GPS on/off (G)", "jam", "#ffd6d6"), ("Motors off (X)", "disarm", "#ffe8c2"),
    ("Clear track (C)", "clear", "#eeeeee"), ("Quit (Esc)", "quit", "#eeeeee"),
]
CAM_BUTTONS = [(f"Cam {k}: {CAMERA_VIEWS[k][0]}", k) for k in CAMERA_VIEWS]
_buttons = []
for i, (label, action, colour) in enumerate(BUTTONS):
    b = Button(fig.add_axes((0.02 + i * 0.12, 0.075, 0.115, 0.045)), label, color=colour, hovercolor="#bcd4ff")
    b.label.set_fontsize(9.5)
    b.on_clicked(lambda _e, a=action: act(a))
    _buttons.append(b)
for i, (label, action) in enumerate(CAM_BUTTONS):
    b = Button(fig.add_axes((0.02 + i * 0.192, 0.02, 0.185, 0.04)), label, color="#e9f5ec", hovercolor="#c6ebd0")
    b.label.set_fontsize(9.5)
    b.on_clicked(lambda _e, a=action: act(a))
    _buttons.append(b)

ax.set_xlim(*MAP_EAST); ax.set_ylim(*MAP_NORTH); ax.set_aspect("equal")
ax.set_xlabel("East [m]"); ax.set_ylabel("North [m]"); ax.grid(alpha=0.25)
ax.set_title("Map (top view) — what the drone believes", fontsize=11)
ax.plot([0, B_EAST], [0, B_NORTH], ls="--", color=GREY, lw=1, zorder=1)
ax.scatter([0], [0], s=900, marker="s", color=GREEN, alpha=0.25, zorder=2)
ax.text(0, -3.5, "START", ha="center", va="top", color=GREEN, weight="bold", fontsize=12)
ax.scatter([B_EAST], [B_NORTH], s=700, marker="o", color=RED, alpha=0.25, zorder=2)
ax.scatter([B_EAST], [B_NORTH], s=60, color=RED, zorder=3)
ax.text(B_EAST, B_NORTH + 3, "B", ha="center", color=RED, weight="bold", fontsize=16)
crumbs_plot = ax.scatter([], [], s=28, marker="D", color=GOLD, zorder=3, label="Breadcrumbs (recorded while GPS trusted)")
gps_plot, = ax.plot([], [], ".", color=ORANGE, ms=4, alpha=0.6, label="GPS fixes", zorder=3)
track_ok, = ax.plot([], [], color=BLUE, lw=2, label="Track (GPS OK)", zorder=4)
track_bad, = ax.plot([], [], color=RED, lw=2, ls="--", label="Track (NO GPS — PX4 guessing)", zorder=4)
drone_dot, = ax.plot([], [], marker=(3, 0, 0), ms=18, color="black", zorder=5)
ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

status_box = FancyBboxPatch((0.02, 0.83), 0.96, 0.15, boxstyle="round,pad=0.01", transform=panel.transAxes,
                            color=GREEN, ec="none")
panel.add_patch(status_box)
status_txt = panel.text(0.5, 0.905, "", transform=panel.transAxes, ha="center", va="center",
                        fontsize=17, weight="bold", color="white", linespacing=1.3)
info_txt = panel.text(0.03, 0.79, "", transform=panel.transAxes, va="top", family="monospace", fontsize=10.5)
detect_txt = panel.text(0.03, 0.56, "", transform=panel.transAxes, va="top", family="monospace", fontsize=10.5)
events_txt = panel.text(0.03, 0.40, "", transform=panel.transAxes, va="top", family="monospace", fontsize=8.5,
                        color="#333333")
panel.text(0.03, 0.12, "W A S D / arrows  fly N W S E (map directions)\n"
                       "R / F  up / down      Q / E  rotate\n"
                       "1-5 camera views      click this window for keys",
           transform=panel.transAxes, va="top", family="monospace", fontsize=10, color="#1f3b73",
           bbox=dict(boxstyle="round", fc="#eef3fb", ec="#9db4dd"))


def append_point(series, x, y):
    series[0].append(x); series[1].append(y)


def update(_):
    update_sticks()
    now = time.time()
    with drone.lock:
        connected, n, e, alt, spd = drone.connected, drone.n, drone.e, drone.alt, drone.speed
        mode, armed, yaw, gps_ne = drone.mode, drone.armed, drone.yaw, drone.gps_ne
        last_good, dts, events = drone.last_good_gps, list(drone.gps_dts), list(drone.events)
        fix, sats, pos_valid = drone.gps_fix, drone.gps_sats, drone.pos_valid
        drone.gps_ne = None

    if connected and not state["setup_done"]:
        drone.setup()
        drone.log("parameters set (demo setup)")
        camera.set_view("2", yaw)
        state["setup_done"] = True
    camera.tick(yaw)

    # Home to START: land once we are there (PX4's own RTL would go to the last arming spot)
    if state["homing"] and armed and math.hypot(n, e) < 2.0 and spd < 0.7:
        state["homing"] = False
        drone.log("> at START - landing")
        drone.set_mode(4, 6)

    # Our monitor: GPS silent for longer than GPS_SILENT_LIMIT (and > 3 typical intervals)
    typical = sorted(dts)[len(dts) // 2] if dts else 0.2
    limit = max(GPS_SILENT_LIMIT, 3 * typical)
    gps_ok = last_good is not None and now - last_good < limit
    if not gps_ok and state["prev_gps_ok"] and connected:
        state["monitor_t"] = now
        if state["jam_t"] is None:   # jammed from the PX4 console instead of this app
            state["jam_t"] = last_good or now
        drone.log("OUR MONITOR: GPS LOST -> switch to IMU + own map")
    state["prev_gps_ok"] = gps_ok
    if drone.last_failsafe and state["px4_t"] is None and state["jam_t"] and drone.last_failsafe >= state["jam_t"]:
        state["px4_t"] = drone.last_failsafe

    # Map
    if pos_valid and armed:
        append_point(state["track_ok"] if gps_ok else state["track_bad"], e, n)
        other = state["track_bad"] if gps_ok else state["track_ok"]
        if other[0] and not math.isnan(other[0][-1]):
            append_point(other, math.nan, math.nan)   # break the other line
        cx, cy = state["crumbs"]
        if gps_ok and alt > 1.0 and (not cx or math.hypot(e - cx[-1], n - cy[-1]) >= BREADCRUMB_SPACING):
            append_point(state["crumbs"], e, n)
    if gps_ne and armed:
        append_point(state["gps_pts"], gps_ne[1], gps_ne[0])
    track_ok.set_data(*state["track_ok"])
    track_bad.set_data(*state["track_bad"])
    gps_plot.set_data(*state["gps_pts"])
    if state["crumbs"][0]:
        crumbs_plot.set_offsets(list(zip(*state["crumbs"])))
    drone_dot.set_data([e], [n])
    drone_dot.set_marker((3, 0, -math.degrees(yaw)))   # triangle points along heading (north-up map)

    # Status
    if not connected:
        status_box.set_color(GREY); status_txt.set_text("WAITING FOR\nSIMULATOR…")
    elif gps_ok:
        status_box.set_color(GREEN); status_txt.set_text(f"GPS TRUSTED\n{fix}D fix, {sats} satellites")
    else:
        status_box.set_color(RED); status_txt.set_text("GPS LOST\njamming detected")

    d_b = math.hypot(n - B_NORTH, e - B_EAST)
    d_home = math.hypot(n, e)
    info_txt.set_text(
        f"Mode      : {mode}{'  (ARMED)' if armed else '  (disarmed)'}\n"
        f"Altitude  : {alt:5.1f} m      Speed: {spd:4.1f} m/s\n"
        f"To B      : {d_b:5.1f} m      To START: {d_home:5.1f} m\n"
        f"Breadcrumbs recorded: {len(state['crumbs'][0])}"
    )
    lines = ["Reaction to GPS loss:"]
    if state["jam_t"]:
        mt, pt = state["monitor_t"], state["px4_t"]
        lines.append(f"  our monitor : {mt - state['jam_t']:4.1f} s" if mt else "  our monitor : …")
        lines.append(f"  PX4 failsafe: {pt - state['jam_t']:4.1f} s" if pt else
                     f"  PX4 failsafe: … ({now - state['jam_t']:.0f} s)")
        if not gps_ok:
            lines.append("  PX4 cannot return home without GPS —")
            lines.append("  -> terrain nav + swarm sharing fix this.")
    else:
        lines.append("  press G to jam the GPS")
    detect_txt.set_text("\n".join(lines))
    events_txt.set_text("Events\n" + "\n".join(events))
    return []


if __name__ == "__main__":
    fig.canvas.mpl_connect("key_press_event", on_press)
    fig.canvas.mpl_connect("key_release_event", on_release)
    anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.show()
    drone.running = False
