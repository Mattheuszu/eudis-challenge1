"""
AI mission brain for a drone in a GPS-contested area  (EUDIS Hackathon 2026)

The Air Force already has systems that detect jamming and fly home. They asked
for the next step: a system that ASSESSES the situation, TELLS others, and FINDS
A SOLUTION itself - for example by circling to learn more, or by creating its
own route.

How it works:
  1. The drone flies its reconnaissance mission.
  2. When jamming is detected, the situation is handed to the mission brain:
     a large language model (Claude) that reasons about it in plain language.
  3. The brain can only act through a few safe tools:
        circle_and_measure  - orbit and locate the jammer from jamming strength
        plan_route          - create its own route around the danger zone,
                              preferring hilly ground where terrain navigation works
        fly_route           - fly a planned route
        broadcast           - send a short report to the fleet / operator
  4. Every tool call passes a safety check (battery reserve, limits) before it runs.
     The model decides WHAT to do; tested code decides HOW to fly it.

Without an API key (or with --offline) a simple rule-based brain makes the same
kind of decisions, so the demo always runs.

Run: python ai_commander.py             (uses Claude if credentials are set up)
     python ai_commander.py --offline   (rule-based brain, no internet needed)
Saves ai_mission.png and ai_mission_log.txt
"""
import heapq
import json
import os
import sys
import textwrap

import numpy as np

import jammer_hunt as J
import sim_long as S

import matplotlib.pyplot as plt  # noqa: E402  (sim_long already selected the Agg backend)

# ---------------- SETTINGS ----------------
MODEL = "claude-opus-5-5"
SPEED = 20.0              # m/s
DT = 1.0                  # s per simulation step
BATTERY_KM = 30.0         # total range of the drone
RESERVE_KM = 3.0          # never plan below this reserve
DETECT_DB = 8.0           # jamming level that triggers the brain (average of the last 10 readings)
GPS_LOST_DB = J.GPS_LOST_DB
IMU_BIAS = 0.02           # m/s^2, drift when GPS is lost
TERRAIN_FIX_EVERY = 15    # s
MIN_RELIEF = 3.0          # m, terrain matching needs at least this much ground shape
GRID = 100.0              # m, route-planning grid
SEED = 5

HOME = S.START.copy()
MISSION_ROUTE = S.ROUTE.copy()
DESTINATION = S.DESTINATION.copy()
X_RANGE, Y_RANGE = (-1500.0, 10500.0), (-2000.0, 5000.0)


def relief(xy):
    """How much shape the ground has around each point (std of height within ±300 m)."""
    xy = np.atleast_2d(xy)
    o = np.linspace(-300, 300, 7)
    ox, oy = np.meshgrid(o, o)
    h = S.terrain(xy[:, None, 0] + ox.ravel(), xy[:, None, 1] + oy.ravel())
    return h.std(axis=1)


# Planning grid and its terrain quality, computed once
_gx = np.arange(X_RANGE[0], X_RANGE[1], GRID)
_gy = np.arange(Y_RANGE[0], Y_RANGE[1], GRID)
_GX, _GY = np.meshgrid(_gx, _gy)
RELIEF_GRID = relief(np.stack([_GX.ravel(), _GY.ravel()], 1)).reshape(_GX.shape)


class World:
    """The simulated drone and its surroundings."""

    def __init__(self, seed=SEED):
        self.rng = np.random.default_rng(seed)
        self.true = HOME.copy()
        self.err = np.zeros(2)          # navigation error (estimate - truth)
        self.vel_err = np.zeros(2)
        self.bias = IMU_BIAS * np.array([0.8, -0.6])
        self.t = 0.0
        self.flown_km = 0.0
        self.no_gps_s = 0.0
        self.last_fix = 0.0
        self.track = []                 # (t, true x, true y, gps ok)
        self.readings_pos, self.readings_db = [], []
        self.recent_db = []
        self.threat = None
        self.plans = {}
        self.flown_plans = []
        self.circles = []
        self.comms = []
        self.log = []
        self.mission_done = False

    # --- sensors -----------------------------------------------------------
    @property
    def est(self):
        return self.true + self.err

    def jam_db(self):
        return float(J.heard(J.jn_db(self.true, J.JAMMER, J.JAMMER_POWER)) + self.rng.normal(0, J.SHADOWING))

    def gps_ok(self):
        return J.jn_db(self.true, J.JAMMER, J.JAMMER_POWER) < GPS_LOST_DB

    def battery_left_km(self):
        return BATTERY_KM - self.flown_km

    def jamming_detected(self):
        return len(self.recent_db) >= 10 and np.mean(self.recent_db[-10:]) > DETECT_DB

    # --- motion ------------------------------------------------------------
    def step_towards(self, target):
        d = target - self.est
        dist = np.linalg.norm(d)
        move = min(SPEED * DT, dist)
        if dist > 0:
            self.true = self.true + d / dist * move
        self.flown_km += move / 1000
        self.t += DT
        if self.gps_ok():
            self.err = self.rng.normal(0, 3.0, 2)
            self.vel_err *= 0.0
            self.last_fix = self.t
        else:
            # GPS lost: IMU drift, corrected by terrain matching where the ground has shape
            self.no_gps_s += DT
            self.vel_err += (self.bias + self.rng.normal(0, 0.05, 2)) * DT
            self.err = self.err + self.vel_err * DT
            if self.t - self.last_fix >= TERRAIN_FIX_EVERY and relief(self.true)[0] >= MIN_RELIEF:
                self.err = self.rng.normal(0, 12.0, 2)
                self.vel_err *= 0.3
                self.last_fix = self.t
        level = self.jam_db()
        self.recent_db.append(level)
        self.readings_pos.append(self.est.copy())
        self.readings_db.append(level)
        self.track.append((self.t, *self.true, self.gps_ok()))
        return move

    def fly_waypoints(self, waypoints, stop_when=None, max_s=3000):
        """Fly through waypoints (in estimated coordinates). Returns True if stopped early."""
        start = self.t
        for wp in waypoints:
            while np.linalg.norm(wp - self.est) > 15 and self.t - start < max_s:
                self.step_towards(wp)
                if stop_when and stop_when():
                    return True
        return False

    def say(self, who, text):
        line = f"[t={self.t:5.0f} s] {who}: {text}"
        self.log.append(line)
        print(line)


# ---------------- TOOLS (what the brain is allowed to do) ----------------
def tool_circle_and_measure(w, radius_m, laps):
    need_km = 2 * np.pi * radius_m * laps / 1000
    if need_km > w.battery_left_km() - RESERVE_KM:
        raise ValueError(f"not enough battery: circling needs {need_km:.1f} km, "
                         f"only {w.battery_left_km() - RESERVE_KM:.1f} km above reserve")
    center = w.est.copy()
    ang = np.arctan2(*(w.est - center + [1e-9, 0])[::-1])
    th = ang + np.linspace(0, 2 * np.pi * laps, int(24 * laps) + 1)[1:]
    pts = center + radius_m * np.stack([np.cos(th), np.sin(th)], 1)
    t0 = w.t
    w.fly_waypoints(pts)
    w.circles.append((center, radius_m))
    est, power, GX, GY, region = J.locate(np.array(w.readings_pos), np.array(w.readings_db))
    area = region.sum() * J.GRID**2 / 1e6
    red = J.red_zone_radius(power)
    rel = est - w.est
    w.threat = {"position": est, "red_zone_m": red, "area_km2": area, "region": (GX, GY, region)}
    return {
        "jammer_estimate_east_north_m": [round(float(est[0])), round(float(est[1]))],
        "distance_from_drone_m": round(float(np.linalg.norm(rel))),
        "bearing_deg": round(float(np.degrees(np.arctan2(rel[0], rel[1]))) % 360),
        "uncertainty_area_km2_95pct": round(area, 2),
        "gps_lost_within_m": round(red),
        "readings_used": len(w.readings_db),
        "time_spent_s": round(w.t - t0),
        "battery_left_km": round(w.battery_left_km(), 1),
    }


def astar(start, goal, blocked, extra_cost=None):
    """Shortest path on the planning grid. Flat ground costs 50 % extra (terrain
    navigation works badly there), extra_cost (0..) is added per cell, blocked
    cells are never entered."""
    ny, nx = blocked.shape

    def cell(p):
        return (int(np.clip(round((p[1] - Y_RANGE[0]) / GRID), 0, ny - 1)),
                int(np.clip(round((p[0] - X_RANGE[0]) / GRID), 0, nx - 1)))

    s, g = cell(start), cell(goal)
    blocked = blocked.copy()
    blocked[s] = blocked[g] = False
    weight = np.where(RELIEF_GRID < MIN_RELIEF, 1.5, 1.0)
    if extra_cost is not None:
        weight = weight + extra_cost
    dist = {s: 0.0}
    prev = {}
    pq = [(0.0, s)]
    while pq:
        _, c = heapq.heappop(pq)
        if c == g:
            break
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                n = (c[0] + dy, c[1] + dx)
                if (dy or dx) and 0 <= n[0] < ny and 0 <= n[1] < nx and not blocked[n]:
                    step = GRID * np.hypot(dy, dx) * weight[n]
                    nd = dist[c] + step
                    if nd < dist.get(n, np.inf):
                        dist[n], prev[n] = nd, c
                        h = GRID * np.hypot(n[0] - g[0], n[1] - g[1])
                        heapq.heappush(pq, (nd + h, n))
    if g not in prev and g != s:
        return None
    path, c = [g], g
    while c != s:
        c = prev[c]
        path.append(c)
    pts = np.array([[_gx[c[1]], _gy[c[0]]] for c in path[::-1]])
    keep = [0] + [i for i in range(1, len(pts) - 1) if i % 6 == 0] + [len(pts) - 1]
    pts = pts[keep]
    pts[0], pts[-1] = start, goal
    return pts


def tool_plan_route(w, goal, safety_margin_m):
    target = DESTINATION if goal == "destination" else HOME
    blocked = np.zeros(_GX.shape, bool)
    extra = None
    if w.threat:
        # Hard no-go: estimated GPS-loss zone + margin. Soft: where the jammer might also be.
        d = np.hypot(_GX - w.threat["position"][0], _GY - w.threat["position"][1])
        unsure = np.sqrt(w.threat["area_km2"] * 1e6 / np.pi)
        keep_out = w.threat["red_zone_m"] + safety_margin_m
        blocked = d < keep_out
        extra = np.where(d < keep_out + unsure, 2.0, 0.0)
        drone_d = np.hypot(*(w.est - w.threat["position"]))
        if drone_d < keep_out:
            raise ValueError(f"drone is already inside the keep-out radius ({drone_d:.0f} m < {keep_out:.0f} m); "
                             "use a smaller safety margin")
    pts = astar(w.est.copy(), target, blocked, extra)
    if pts is None:
        raise ValueError("no route found that avoids the danger zone")
    length = np.linalg.norm(np.diff(pts, axis=0), axis=1).sum() / 1000
    dense = np.concatenate([np.linspace(a, b, 20) for a, b in zip(pts[:-1], pts[1:])])
    good = float((relief(dense) >= MIN_RELIEF).mean())
    min_jam = float(np.min(np.linalg.norm(dense - w.threat["position"], axis=1))) if w.threat else None
    route_id = f"R{len(w.plans) + 1}"
    w.plans[route_id] = {"goal": goal, "points": pts}
    return {
        "route_id": route_id,
        "goal": goal,
        "length_km": round(length, 1),
        "battery_after_km": round(w.battery_left_km() - length, 1),
        "battery_ok": bool(w.battery_left_km() - length >= RESERVE_KM),
        "share_over_hilly_ground": round(good, 2),
        "closest_to_estimated_jammer_m": None if min_jam is None else round(min_jam),
        "keep_out_radius_m": round(float(keep_out)) if w.threat else 0,
    }


def tool_fly_route(w, route_id):
    if route_id not in w.plans:
        raise ValueError(f"unknown route {route_id}; plan one first")
    plan = w.plans[route_id]
    length = np.linalg.norm(np.diff(plan["points"], axis=0), axis=1).sum() / 1000
    if length > w.battery_left_km() - RESERVE_KM:
        raise ValueError(f"route needs {length:.1f} km but only {w.battery_left_km() - RESERVE_KM:.1f} km above reserve")
    t0, no_gps0 = w.t, w.no_gps_s
    w.fly_waypoints(plan["points"])
    w.flown_plans.append(route_id)
    target = DESTINATION if plan["goal"] == "destination" else HOME
    miss = float(np.linalg.norm(w.true - target))
    w.mission_done = plan["goal"] == "destination" and miss < 100
    return {
        "arrived": bool(miss < 100),
        "real_distance_to_goal_m": round(miss),
        "time_s": round(w.t - t0),
        "seconds_without_gps": round(w.no_gps_s - no_gps0),
        "battery_left_km": round(w.battery_left_km(), 1),
    }


def tool_broadcast(w, recipient, priority, message):
    jammed = J.jn_db(w.true, J.JAMMER, J.JAMMER_POWER) > GPS_LOST_DB
    w.comms.append((w.t, recipient, priority, message))
    w.say(f"BROADCAST to {recipient} [{priority.upper()}]", message)
    return {"status": "queued, link jammed - sends when clear" if jammed else "delivered"}


TOOL_FUNCS = {
    "circle_and_measure": tool_circle_and_measure,
    "plan_route": tool_plan_route,
    "fly_route": tool_fly_route,
    "broadcast": tool_broadcast,
}

TOOLS = [
    {
        "name": "circle_and_measure",
        "description": "Fly circles around the current position while measuring jamming strength, "
                       "then estimate where the jammer is (position, uncertainty area, radius where GPS is lost). "
                       "Costs time and battery; worth it when the jammer position is unknown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "radius_m": {"type": "integer", "description": "Circle radius in metres, 150-800"},
                "laps": {"type": "integer", "description": "Number of laps, 1-3"},
            },
            "required": ["radius_m", "laps"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "plan_route",
        "description": "Create a new route from the current position to the mission destination or home. "
                       "It avoids the estimated danger zone plus the safety margin and prefers hilly ground "
                       "where GPS-free terrain navigation works. Returns length, battery after, and a route_id. "
                       "Does not fly it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "enum": ["destination", "home"]},
                "safety_margin_m": {"type": "integer", "description": "Extra distance kept from the danger zone, 0-1500"},
            },
            "required": ["goal", "safety_margin_m"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "fly_route",
        "description": "Fly a route created by plan_route. Returns whether the drone arrived, the real distance "
                       "to the goal, and how long it flew without GPS.",
        "input_schema": {
            "type": "object",
            "properties": {"route_id": {"type": "string"}},
            "required": ["route_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "broadcast",
        "description": "Send a short report to the other drones, the operator, or both. Use it to share the threat "
                       "(jammer position, danger zone) and your decision. Keep messages short and factual.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "enum": ["fleet", "operator", "all"]},
                "priority": {"type": "string", "enum": ["routine", "priority", "flash"]},
                "message": {"type": "string"},
            },
            "required": ["recipient", "priority", "message"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

LIMITS = {"radius_m": (150, 800), "laps": (1, 3), "safety_margin_m": (0, 1500)}


def execute(w, name, args):
    """Safety layer: check every request before the drone does anything."""
    if name not in TOOL_FUNCS:
        return {"error": f"unknown tool {name}"}, True
    for key, (lo, hi) in LIMITS.items():
        if key in args and not lo <= args[key] <= hi:
            return {"error": f"{key} must be between {lo} and {hi}"}, True
    w.say("ACTION", f"{name} {json.dumps(args, ensure_ascii=False)}")
    try:
        result = TOOL_FUNCS[name](w, **args)
    except ValueError as e:
        w.say("SAFETY CHECK", f"refused: {e}")
        return {"error": str(e)}, True
    if name != "broadcast":
        w.say("RESULT", json.dumps(result, ensure_ascii=False))
    return result, False


# ---------------- THE BRAINS ----------------
SYSTEM = """You are the mission brain of a small reconnaissance drone in a GPS-contested area.
Your mission is to reach the destination and observe it. Home is the launch point.

Priorities, in order:
1. Do not lose the aircraft: never plan below the battery reserve, avoid the danger zone.
2. Complete the mission if it can be done safely; otherwise come home.
3. Tell others: the fleet and operator must learn about the threat and your decision.

You act only through the tools. Before acting, give a short assessment in plain language:
what is happening, what you know and don't know, and what you will do and why.
Use real numbers from the situation report and tool results; never invent them.
Broadcasts are read by soldiers under pressure: short, factual, no filler.
When you are finished, end with a one-paragraph summary for the operator."""


def situation_report(w):
    lv = np.array(w.recent_db[-30:])
    trend = lv[-5:].mean() - lv[:5].mean() if len(lv) >= 10 else 0.0
    to_dest = np.linalg.norm(DESTINATION - w.est) / 1000
    return (
        "SITUATION REPORT\n"
        f"- Time since launch: {w.t:.0f} s\n"
        f"- Position (east, north): {w.est.round().tolist()} m; home {HOME.tolist()}, destination {DESTINATION.tolist()}\n"
        f"- GPS: {'still working' if w.gps_ok() else 'LOST'}; navigation can fall back to terrain matching (laser + height map)\n"
        f"- Jamming detected: level {lv[-1]:.1f} dB above normal noise, rising {trend:+.1f} dB over the last 30 s\n"
        f"- Jammer position: unknown\n"
        f"- Distance to destination: {to_dest:.1f} km on the planned route, which heads towards the jamming\n"
        f"- Battery: {w.battery_left_km():.1f} km left, reserve {RESERVE_KM:.0f} km\n"
        "Decide what to do."
    )


def llm_brain(w, report):
    import anthropic
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": report}]
    for _ in range(15):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason == "refusal":
            w.say("BRAIN", "declined to decide - handing over to the rule-based brain")
            return False
        for block in response.content:
            if block.type == "text" and block.text.strip():
                w.say("BRAIN", block.text.strip())
        if response.stop_reason != "tool_use":
            return True
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                out, is_err = execute(w, block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out), "is_error": is_err})
        messages.append({"role": "user", "content": results})
    return True


def rule_brain(w, report):
    """Fallback without a language model: the same tools, fixed rules."""
    w.say("BRAIN (rules)", "Jamming is rising ahead and the jammer position is unknown. "
                           "Battery allows a short orbit, so measure first, then decide.")
    res, err = execute(w, "circle_and_measure", {"radius_m": 800, "laps": 1})
    if err:
        res = None
    if res:
        execute(w, "broadcast", {
            "recipient": "all", "priority": "flash",
            "message": f"GNSS jammer est. at E{res['jammer_estimate_east_north_m'][0]} "
                       f"N{res['jammer_estimate_east_north_m'][1]} (±{res['uncertainty_area_km2_95pct']} km²). "
                       f"GPS lost within {res['gps_lost_within_m']} m. Avoid. Rerouting to continue mission."})
    plan, err = execute(w, "plan_route", {"goal": "destination", "safety_margin_m": 400})
    if err or not plan["battery_ok"]:
        plan, err = execute(w, "plan_route", {"goal": "home", "safety_margin_m": 400})
    if not err:
        out, _ = execute(w, "fly_route", {"route_id": plan["route_id"]})
        execute(w, "broadcast", {
            "recipient": "operator", "priority": "priority",
            "message": f"{'Arrived at destination' if out['arrived'] else 'Did not arrive'}: "
                       f"{out['real_distance_to_goal_m']} m from goal, {out['seconds_without_gps']} s without GPS, "
                       f"{out['battery_left_km']} km battery left."})
    return True


def have_credentials():
    return any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))


# ---------------- MISSION ----------------
def run_mission(use_llm):
    w = World()
    w.say("MISSION", f"Launch. Reconnaissance flight to {DESTINATION.tolist()}.")
    stopped = w.fly_waypoints(MISSION_ROUTE, stop_when=w.jamming_detected)
    if stopped:
        w.say("DETECT", f"Jamming detected ({w.recent_db[-1]:.1f} dB). Handing over to the mission brain.")
        report = situation_report(w)
        ok = False
        if use_llm:
            try:
                ok = llm_brain(w, report)
            except Exception as e:  # network / credentials: never leave the drone without a brain
                w.say("BRAIN", f"language model unavailable ({type(e).__name__}) - using rule-based brain")
        if not ok:
            rule_brain(w, report)
    if not w.mission_done and not w.flown_plans:
        w.say("MISSION", "No new route chosen - continuing the original route.")
        w.fly_waypoints([DESTINATION])
        w.mission_done = np.linalg.norm(w.true - DESTINATION) < 100
    return w


def run_baseline():
    """What the existing system does: detect GPS loss, then fly home."""
    w = World()
    w.fly_waypoints(MISSION_ROUTE, stop_when=lambda: not w.gps_ok())
    t_lost = w.t
    w.fly_waypoints([HOME])
    return w, t_lost


def plot(w, base, t_lost, brain_name):
    fig = plt.figure(figsize=(20, 9))
    ax = fig.add_axes([0.03, 0.08, 0.55, 0.82])
    axt = fig.add_axes([0.6, 0.05, 0.39, 0.85])
    X, Y = np.meshgrid(np.linspace(-500, 9500, 250), np.linspace(-1500, 4800, 160))
    ax.contourf(X, Y, S.terrain(X, Y), levels=20, cmap="Greys", alpha=0.4)
    ax.plot(*np.vstack([HOME, MISSION_ROUTE]).T, "--", color="black", lw=1, label="Planned mission route")

    th = np.linspace(0, 2 * np.pi, 100)
    true_r = J.red_zone_radius(J.JAMMER_POWER)
    ax.fill(J.JAMMER[0] + true_r * np.cos(th), J.JAMMER[1] + true_r * np.sin(th), color="#cf222e", alpha=0.12)
    ax.scatter(*J.JAMMER, s=160, marker="X", color="black", zorder=6, label="Real jammer (unknown to drone)")

    bt = np.array([p[1:3] for p in base.track])
    ax.plot(bt[:, 0], bt[:, 1], color="#e8710a", lw=2, alpha=0.8,
            label=f"Existing system: GPS lost at {t_lost:.0f} s -> flies home, mission aborted")
    tr = np.array([p[1:3] for p in w.track])
    ax.plot(tr[:, 0], tr[:, 1], color="#2a6fdb", lw=2.5, label=f"With {brain_name}: real path")

    if w.threat:
        GX, GY, reg = w.threat["region"]
        ax.contour(GX, GY, reg.astype(float), levels=[0.5], colors="#cf222e", linewidths=2)
        p = w.threat["position"]
        ax.scatter(*p, s=170, marker="^", color="#cf222e", edgecolor="black", zorder=7,
                   label=f"Estimated jammer ({np.linalg.norm(p - J.JAMMER):.0f} m off)")
        r = w.threat["red_zone_m"]
        ax.plot(p[0] + r * np.cos(th), p[1] + r * np.sin(th), color="#cf222e", lw=1.5, ls="--",
                label="Estimated zone where GPS is lost")
    for rid in w.flown_plans:
        pts = w.plans[rid]["points"]
        ax.plot(pts[:, 0], pts[:, 1], "o:", color="#1a7f37", ms=4, lw=1.5, label=f"Route {rid} created by the brain")
    ax.scatter(*HOME, s=130, color="green", zorder=7, label="Home")
    ax.scatter(*DESTINATION, s=300, marker="*", color="red", zorder=7, label="Mission destination")
    ax.set_xlim(-500, 9500); ax.set_ylim(-1500, 4800); ax.set_aspect("equal")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.set_title("Map (grey = hills)", fontsize=13)

    axt.axis("off")
    lines = []
    for line in w.log:
        lines += textwrap.wrap(line, 82, subsequent_indent="      ")[:8]
    axt.text(0, 1, "Mission log\n\n" + "\n".join(lines[:70]), va="top", ha="left", family="monospace", fontsize=9)
    outcome = "mission completed" if w.mission_done else "mission not completed"
    fig.suptitle(f"AI mission brain ({brain_name}): assess, tell others, find a way - {outcome}, "
                 f"{len(w.comms)} reports sent", fontsize=15, weight="bold")
    plt.savefig("ai_mission.png", dpi=100)


def main():
    use_llm = "--offline" not in sys.argv and have_credentials()
    brain_name = f"Claude, {MODEL}" if use_llm else "offline rule-based brain"
    if not use_llm and "--offline" not in sys.argv:
        print("No Anthropic credentials found (ANTHROPIC_API_KEY) - running the rule-based brain.\n")
    w = run_mission(use_llm)
    base, t_lost = run_baseline()
    print(f"\nExisting system: GPS lost at {t_lost:.0f} s, flew home, mission aborted.")
    print(f"With the mission brain: {'mission completed' if w.mission_done else 'mission NOT completed'}, "
          f"{w.flown_km:.1f} km flown, {w.no_gps_s:.0f} s without GPS, {len(w.comms)} reports sent.")
    with open("ai_mission_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(w.log) + "\n")
    plot(w, base, t_lost, brain_name)
    print("Saved ai_mission.png and ai_mission_log.txt")


if __name__ == "__main__":
    main()
