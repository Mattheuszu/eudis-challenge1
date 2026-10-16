"""Swarm reroute: DETECT -> LOCATE -> SHARE -> REROUTE  (EUDIS Hackathon 2026)

What the military asked for: detect + return home already exists. New idea:
when one drone is jammed, it warns the others and the swarm still completes
the mission by planning around the danger zone.

Three drones fly to a target. A hidden jammer sits across their routes.
Three scenarios:
  1. Today        - standard autopilot: GPS lost -> blind descent after ~5 s,
                    the drone comes down inside the jammed (enemy) area.
  2. Each alone   - our detector (~1 s) + retrace own breadcrumbs to get GPS
                    back + reroute. Every drone has to find the zone itself.
  3. Swarm shares - the first jammed drone (scout) broadcasts what it measured.
                    Everyone pools interference readings, estimates where GPS
                    dies, and plans around it before flying in.

Localisation: GPS receivers report interference level (PX4: jamming_indicator,
noise, AGC). Free-space model + 3 dB shadowing, grid search over jammer
position and power (same idea as jammer_hunt.py). The no-go area is every
place where GPS dies with > 15 % probability over the plausible jammers (95 %
region) -> covers both sides when a single straight track can't tell the mirror
spot apart, plus a hard radius around every point where GPS really died.
Planning: A* on a 50 m grid + line-of-sight smoothing. Deterministic and
explainable; the decision log is what an LLM "mission advisor" would phrase
for the operator - the LLM advises, it does not fly.

Run: python swarm_reroute.py          (saves swarm_reroute.png)
     python swarm_reroute.py --gif    (also swarm_reroute.gif, scenario 3 animated)
"""
import heapq
import math
import sys

import matplotlib.pyplot as plt
import numpy as np

# ---------------- SETTINGS (play with these) ----------------
JAMMER = np.array([2700.0, 2150.0])   # m (East, North), hidden from the drones
JAMMER_POWER = 72.0      # dB at 1 m -> GPS dies within ~700 m
SHADOWING = 3.0          # dB random variation (terrain, multipath)
GPS_LOST_DB = 15.0       # interference above this -> GPS lost
GPS_BACK_DB = 13.0       # below this -> GPS back (hysteresis)
HEARD_MIN_DB = 6.0       # readings below this are just noise, not used
FLY_HEIGHT = 120.0       # m
SPEED = 15.0             # m/s
DT = 1.0                 # s
READ_EVERY = 4           # s between interference readings
GPS_NOISE = 1.5          # m
IMU_BIAS = 0.02          # m/s^2 (same order as Guled's sim)
IMU_NOISE = 0.02         # m/s^2
OUR_ALARM_DELAY = 1.0    # s, our GPS monitor (measured in the live demo)
PX4_FAILSAFE_DELAY = 5.0 # s, PX4 failsafe (measured in 2/2 SITL flights)
UPDATE_EVERY = 20        # s between threat-map updates
NOGO_MARGIN_DB = 3.0     # plan this much "quieter" than GPS_LOST (safety margin)
# Fake-report attack (Guled's question): a captured drone with a VALID key flies with the
# swarm and reports invented interference readings, to push the swarm's danger map away
# from the real jammer so the drones plan straight into it.
ATTACKER = "Drone 4 (captured)"
FAKE_JAMMER = np.array([2700.0, 3700.0])   # where the attacker pretends the jammer is
FAKE_POWER = 72.0                          # dB
# claimed path straight over the REAL jammer, reporting "almost quiet here" -> hides it
ATTACK_FROM, ATTACK_TO = np.array([0.0, 2150.0]), np.array([5500.0, 2150.0])
EVIDENCE_RADIUS = 300.0  # m, readings this close to a real GPS-loss point must show strong jamming
NOGO_PROB = 0.15        # avoid cells where GPS dies with > 15 % probability
DEAD_RADIUS = 450.0      # m, around every point where a drone actually lost GPS = surely no-go
CLEAR_AFTER_GPS = 12     # s, keep backing out after GPS returns before planning
TARGET = np.array([5500.0, 2000.0])
DRONES = [  # name, start, departure time, colour
    ("Drone 1", (0.0, 2000.0), 0, "#2a6fdb"),
    ("Drone 2", (0.0, 1200.0), 40, "#8a63d2"),
    ("Drone 3", (0.0, 2800.0), 80, "#1a9e8f"),
]
AREA_E, AREA_N = (-300.0, 6300.0), (0.0, 4000.0)
PLAN_CELL = 50.0
LOC_CELL = 100.0
POWERS = np.arange(60.0, 85.01, 1.0)
MAX_READINGS = 160       # keep the pooled data small enough for a laptop
T_MAX = 900
SEED = 4
# --------------------------------------------------------------

rng = np.random.default_rng(SEED)


def jn_db(xy, jammer, power):
    d2 = ((np.asarray(xy) - jammer) ** 2).sum(-1) + FLY_HEIGHT**2
    return power - 10 * np.log10(d2)


def heard(jn):
    return 10 * np.log10(1 + 10 ** (np.asarray(jn) / 10))


TRUE_RADIUS = math.sqrt(10 ** ((JAMMER_POWER - GPS_LOST_DB) / 10) - FLY_HEIGHT**2)

# planning grid
PE = np.arange(AREA_E[0], AREA_E[1] + 1, PLAN_CELL)
PN = np.arange(AREA_N[0], AREA_N[1] + 1, PLAN_CELL)
PGE, PGN = np.meshgrid(PE, PN)                      # shape (nN, nE)
PLAN_PTS = np.stack([PGE.ravel(), PGN.ravel()], 1)
# localisation candidates
LE = np.arange(AREA_E[0], AREA_E[1] + 1, LOC_CELL)
LN = np.arange(AREA_N[0], AREA_N[1] + 1, LOC_CELL)
LGE, LGN = np.meshgrid(LE, LN)
CANDS = np.stack([LGE.ravel(), LGN.ravel()], 1)


class Threat:
    """Pooled interference readings -> plausible jammer positions -> no-go mask."""

    def __init__(self, defense=False):
        self.pts, self.levels, self.senders = [], [], []
        self.mask = np.zeros(PGE.shape, bool)
        self.version = 0
        self.area_km2 = 0.0
        self.best = None
        self._n_used = 0
        self.dead = []          # where drones actually lost GPS (hard evidence)
        self.defense = defense  # consistency check against the other drones' readings
        self.rejected = {}      # sender -> reason it was rejected

    def mark_dead(self, pos):
        self.dead.append(pos.copy())
        self._n_used = -1

    def add(self, pos, level, sender="?"):
        self.pts.append(pos.copy())
        self.levels.append(level)
        self.senders.append(sender)
        if len(self.pts) > MAX_READINGS:      # thin out: keep every second reading
            self.pts, self.levels, self.senders = self.pts[::2], self.levels[::2], self.senders[::2]
            self._n_used = -1

    @staticmethod
    def fit(pts, lev):
        """Grid search: for every candidate jammer position the best power and the squared error."""
        fall = -10 * np.log10(((pts[None] - CANDS[:, None]) ** 2).sum(-1) + FLY_HEIGHT**2)
        sse = np.full(len(CANDS), np.inf)
        power = np.zeros(len(CANDS))
        for p in POWERS:
            s = ((lev - heard(p + fall)) ** 2).sum(1)
            better = s < sse
            sse[better], power[better] = s[better], p
        return sse, power

    def check_senders(self, pts, lev, snd):
        """Leave-one-sender-out consistency test (works even if the liar has a valid key).
        Fit ONE jammer to everyone else, then to everyone else + this sender. Honest
        readings fit the same physics, so the joint error grows only by their own noise
        (about n * SHADOWING^2). A liar's readings can't be explained by the same jammer,
        so the joint error jumps. Reject when the jump is beyond a 99.9 % noise level."""
        keep = np.ones(len(lev), bool)

        # 1. Hard evidence: where a drone REALLY lost GPS the interference was >= GPS_LOST_DB.
        #    A sender claiming "almost quiet" right there contradicts physics -> liar.
        #    (Fake WARNINGS are not checked here: believing them only costs a detour.)
        if self.dead:
            dead = np.array(self.dead)
            near = (((pts[:, None] - dead[None]) ** 2).sum(-1) < EVIDENCE_RADIUS**2).any(1)
            for s in [s for s in dict.fromkeys(snd) if s not in self.rejected]:
                sel = near & (snd == s)
                if sel.sum() >= 3 and np.median(lev[sel]) < GPS_LOST_DB - 2 * SHADOWING:
                    self.rejected[s] = (f"claims {np.median(lev[sel]):.0f} dB where another drone really lost GPS "
                                        f"(needs >= {GPS_LOST_DB:.0f} dB)")

        # 2. Consistency: can ONE jammer explain everyone's readings?
        def misfit(sel):
            """Normalised error of ONE jammer explaining these readings: ~1 if consistent."""
            n = int(sel.sum())
            return self.fit(pts[sel], lev[sel])[0].min() / (SHADOWING**2 * max(n - 3, 1)), n

        while True:     # is the trusted set consistent? if not, drop the sender whose removal fixes it
            names = [s for s in dict.fromkeys(snd) if s not in self.rejected]
            trusted = np.isin(snd, names)
            q_all, n_all = misfit(trusted)
            if q_all < 1 + 3.1 * math.sqrt(2 / n_all):     # within 99.9 % of honest noise: done
                break
            best, best_q = None, q_all
            for s in names:
                rest = trusted & (snd != s)
                if (snd == s).sum() < 6 or rest.sum() < 8 or len(set(snd[rest])) < 2:
                    continue    # not enough independent data to judge this sender yet
                q, _ = misfit(rest)
                if q < best_q:
                    best, best_q = s, q
            if best is None or best_q > 0.8 * q_all:        # no single sender explains the conflict
                break
            mine = trusted & (snd == best)
            self.rejected[best] = (f"its readings can't be explained by the same jammer as the others' "
                                   f"(misfit {q_all:.1f} -> {best_q:.1f} without it)")
        for s in self.rejected:
            keep &= snd != s
        return keep

    def update(self):
        if len(self.pts) < 8 or len(self.pts) == self._n_used:
            return False
        self._n_used = len(self.pts)
        pts, lev = np.array(self.pts), np.array(self.levels)
        if self.defense:
            keep = self.check_senders(pts, lev, np.array(self.senders))
            pts, lev = pts[keep], lev[keep]
            if len(lev) < 8:
                return False
        sse, power = self.fit(pts, lev)
        plaus = np.flatnonzero((sse - sse.min()) / SHADOWING**2 < 5.99)   # 95 % region
        self.best = CANDS[sse.argmin()]
        self.area_km2 = len(plaus) * LOC_CELL**2 / 1e6
        # probability that GPS is dead in each cell, averaged over plausible jammers
        weight = np.exp(-(sse[plaus] - sse.min()) / (2 * SHADOWING**2))
        top = plaus[np.argsort(-weight)[:150]]
        weight = np.exp(-(sse[top] - sse.min()) / (2 * SHADOWING**2))
        p_dead = np.zeros(len(PLAN_PTS))
        for c, w in zip(top, weight):
            p_dead += w * (jn_db(PLAN_PTS, CANDS[c], power[c]) > GPS_LOST_DB - NOGO_MARGIN_DB)
        mask = p_dead / weight.sum() > NOGO_PROB
        for p in self.dead:
            mask |= ((PLAN_PTS - p) ** 2).sum(1) < DEAD_RADIUS**2
        self.mask = mask.reshape(PGE.shape)
        self.version += 1
        return True


def cell_of(p):
    j = int(round((p[0] - AREA_E[0]) / PLAN_CELL))
    i = int(round((p[1] - AREA_N[0]) / PLAN_CELL))
    return min(max(i, 0), len(PN) - 1), min(max(j, 0), len(PE) - 1)


def line_free(a, b, blocked):
    n = max(2, int(np.linalg.norm(b - a) / (PLAN_CELL / 2)))
    for s in np.linspace(0, 1, n):
        if blocked[cell_of(a + s * (b - a))]:
            return False
    return True


def plan(start, goal, mask):
    """A* where no-go cells are allowed but 40x more expensive (so a drone that
    stands at the edge still finds the shortest way out), then line-of-sight
    smoothing. Returns waypoints."""
    if line_free(start, goal, mask):
        return [goal.copy()]
    si, sj = cell_of(start)
    gi, gj = cell_of(goal)
    nN, nE = mask.shape
    open_ = [(0.0, (si, sj))]
    g = {(si, sj): 0.0}
    came = {}
    steps = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1),
             (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    done = set()
    while open_:
        _, cur = heapq.heappop(open_)
        if cur in done:
            continue
        done.add(cur)
        if cur == (gi, gj):
            break
        for di, dj, c in steps:
            nb = (cur[0] + di, cur[1] + dj)
            if not (0 <= nb[0] < nN and 0 <= nb[1] < nE):
                continue
            ng = g[cur] + c * (40.0 if mask[nb] else 1.0)
            if ng < g.get(nb, np.inf):
                g[nb], came[nb] = ng, cur
                heapq.heappush(open_, (ng + math.hypot(nb[0] - gi, nb[1] - gj), nb))
    cells = [(gi, gj)]
    while cells[-1] in came:
        cells.append(came[cells[-1]])
    pts = [np.array([PE[j], PN[i]]) for i, j in reversed(cells)]
    pts[0], pts[-1] = start.copy(), goal.copy()
    path, k = [pts[0]], 0             # string pulling, never shortcut through no-go cells
    while k < len(pts) - 1:
        m = len(pts) - 1
        while m > k + 1 and not line_free(pts[k], pts[m], mask):
            m -= 1
        path.append(pts[m])
        k = m
    return path[1:]


def route_free(start, wps, mask):
    pts = [start] + list(wps)
    return all(line_free(a, b, mask) for a, b in zip(pts[:-1], pts[1:]))


def path_len(start, wps):
    pts = [start] + list(wps)
    return sum(np.linalg.norm(b - a) for a, b in zip(pts[:-1], pts[1:]))


class Drone:
    def __init__(self, name, start, depart, color):
        self.name, self.color, self.depart = name, color, depart
        self.true = np.array(start, float)
        self.est = self.true.copy()
        self.err = np.zeros(2)
        self.verr = np.zeros(2)
        self.bias = IMU_BIAS * np.array([math.cos(a := rng.uniform(0, 2 * math.pi)), math.sin(a)])
        self.gps = True
        self.lost_at = None
        self.alarm = False
        self.blind_s = 0.0
        self.mode = "waiting"
        self.wps = [TARGET.copy()]
        self.crumbs = [self.est.copy()]
        self.hist, self.hist_gps = [self.true.copy()], [True]
        self.plan_version = 0
        self.arrived = None
        self.dist = 0.0
        self.threat = None   # own Threat (alone) or shared Threat (swarm)
        self.clear_at = None
        self.regained = None


def run(scenario, log=None, attack=False, defense=False):
    """scenario: 'today', 'alone', 'swarm'. attack: a captured drone injects fake readings
    (swarm only). defense: consistency check rejects senders that contradict the others.
    Returns drones, shared threat (swarm) and danger-map snapshots for animation."""
    global rng
    rng = np.random.default_rng(SEED)
    attack_rng = np.random.default_rng(SEED + 99)   # separate, so honest randomness is unchanged
    drones = [Drone(*d) for d in DRONES]
    shared = Threat(defense)
    for d in drones:
        d.threat = shared if scenario == "swarm" else Threat(defense)
    reported = set()
    broadcast = False
    snaps = []
    say = (lambda t, s: log.append(f"t={t:4.0f}s  {s}")) if log is not None else (lambda t, s: None)

    for step in range(int(T_MAX / DT)):
        t = step * DT
        for d in drones:
            if t < d.depart or d.mode in ("done", "down"):
                d.hist.append(d.true.copy()); d.hist_gps.append(d.gps)
                continue
            if d.mode == "waiting":
                d.mode = "cruise"
            # sensors
            jn = jn_db(d.true, JAMMER, JAMMER_POWER)
            was = d.gps
            d.gps = jn < (GPS_BACK_DB if not d.gps else GPS_LOST_DB)
            if d.gps:
                d.err = rng.normal(0, GPS_NOISE, 2); d.verr[:] = 0
            else:
                d.verr += (d.bias + rng.normal(0, IMU_NOISE, 2)) * DT
                d.err += d.verr * DT
                d.blind_s += DT
            d.est = d.true + d.err
            if d.gps and np.linalg.norm(d.est - d.crumbs[-1]) > 50:
                d.crumbs.append(d.est.copy())
            if scenario != "today" and step % READ_EVERY == 0:
                level = float(heard(jn)) + rng.normal(0, SHADOWING)
                if level > HEARD_MIN_DB:
                    d.threat.add(d.est, level, d.name)   # tagged with where it THINKS it is

            # GPS lost -> alarm
            if was and not d.gps:
                d.lost_at = t
            if not d.gps and not d.alarm and t - d.lost_at >= (PX4_FAILSAFE_DELAY if scenario == "today" else OUR_ALARM_DELAY):
                d.alarm = True
                if scenario == "today":
                    d.mode = "down"
                    say(t, f"{d.name}: GPS lost -> PX4 failsafe after {PX4_FAILSAFE_DELAY:.0f} s -> blind descent INSIDE jammed area. Mission lost.")
                    continue
                say(t, f"{d.name}: GPS LOST -> our monitor alarm after {OUR_ALARM_DELAY:.0f} s. Blind: retracing own breadcrumbs to last safe point.")
                d.threat.mark_dead(d.crumbs[-1])
                d.mode = "retreat"
                d.wps = [c for c in reversed(d.crumbs[:-1])] or [d.crumbs[0]]
                if scenario == "swarm" and not broadcast:
                    broadcast = True
                    shared.update()
                    say(t, f"{d.name}: BROADCAST interference readings to swarm -> shared danger map "
                           f"(jammer somewhere in {shared.area_km2:.1f} km2).")
            # GPS back after retreat -> reroute
            if d.mode == "retreat" and d.gps and d.clear_at is None:
                d.clear_at = t + CLEAR_AFTER_GPS
                d.regained = t
            if d.mode == "retreat" and d.gps and t >= d.clear_at:
                d.clear_at = None
                d.alarm = False
                drift = np.linalg.norm(d.err)
                d.threat.update()
                d.wps = plan(d.est, TARGET, d.threat.mask)
                d.plan_version = d.threat.version
                d.mode = "cruise"
                say(t, f"{d.name}: GPS back after {d.regained - d.lost_at:.0f} s blind (IMU drift {drift:.0f} m). "
                       f"New route around danger zone: {path_len(d.est, d.wps) / 1000:.2f} km to go.")

        # the captured drone: claims positions along its path and invents readings
        if attack and scenario == "swarm" and step % READ_EVERY == 0:
            u = ATTACK_TO - ATTACK_FROM
            claimed = ATTACK_FROM + u * min(1.0, SPEED * t / np.linalg.norm(u))
            # "almost quiet here": just above the noise floor, so the readings are not filtered out
            fake = max(float(heard(jn_db(claimed, FAKE_JAMMER, FAKE_POWER))), HEARD_MIN_DB + 1.0)
            shared.add(claimed, fake + attack_rng.normal(0, 1.0), ATTACKER)

        # periodic threat-map update (only once someone has been jammed)
        if step % UPDATE_EVERY == 0 and scenario != "today":
            for th in ({id(d.threat): d.threat for d in drones if scenario == "swarm" and broadcast or d.alarm or d.plan_version}).values():
                th.update()
        for who, why in shared.rejected.items():
            if who not in reported:
                reported.add(who)
                say(t, f"CONSISTENCY CHECK: rejected all reports from {who} - {why}.")
        # replan drones that fly with GPS when their map changed
        for d in drones:
            if d.mode == "cruise" and d.gps and t >= d.depart and d.threat.version != d.plan_version:
                if scenario == "swarm" and not broadcast:
                    continue
                if route_free(d.est, d.wps, d.threat.mask):   # current route still safe: keep it
                    d.plan_version = d.threat.version
                    continue
                old = path_len(d.est, d.wps)
                d.wps = plan(d.est, TARGET, d.threat.mask)
                d.plan_version = d.threat.version
                new = path_len(d.est, d.wps)
                if abs(new - old) > 100:
                    say(t, f"{d.name}: danger map updated -> reroute ({(new - old):+.0f} m, {(new - old) / SPEED:+.0f} s), stays on GPS.")

        # move
        for d in drones:
            if d.mode not in ("cruise", "retreat") or t < d.depart:
                continue
            move = SPEED * DT
            while move > 0 and d.wps:
                vec = d.wps[0] - d.est
                dist = np.linalg.norm(vec)
                if dist <= move:
                    d.true = d.true + vec; d.est = d.est + vec
                    move -= dist; d.dist += dist
                    d.wps.pop(0)
                else:
                    u = vec / dist * move
                    d.true = d.true + u; d.est = d.est + u
                    d.dist += move; move = 0
            if not d.wps:
                if d.mode == "retreat":     # back at the first breadcrumb, still no GPS: wait for GPS
                    d.wps = [d.crumbs[0].copy()]
                elif np.linalg.norm(d.true - TARGET) < 50:
                    d.mode, d.arrived = "done", t
                    say(t, f"{d.name}: reached TARGET ({d.dist / 1000:.2f} km flown, {d.blind_s:.0f} s without GPS).")
            d.hist.append(d.true.copy()); d.hist_gps.append(d.gps)
        snaps.append(shared.mask.copy() if scenario == "swarm" else None)
        if all(d.mode in ("done", "down") for d in drones):
            break
    return drones, (shared if scenario == "swarm" else None), snaps


def summary(drones):
    reached = sum(d.arrived is not None for d in drones)
    blind = sum(d.blind_s for d in drones)
    end = max((d.arrived for d in drones if d.arrived is not None), default=float("nan"))
    km = sum(d.dist for d in drones) / 1000
    return reached, blind, end, km


SCEN = [("today", "1. Today: standard autopilot"),
        ("alone", "2. Our drones, each alone"),
        ("swarm", "3. Our swarm shares the danger map")]

if __name__ == "__main__":
    results = {}
    for key, title in SCEN:
        log = []
        drones, shared, snaps = run(key, log)
        results[key] = (drones, shared, snaps, log)
        r, b, e, km = summary(drones)
        print(f"\n=== {title} ===")
        print("\n".join(log))
        print(f"-> reached target {r}/3 | total time without GPS {b:.0f} s | last arrival "
              f"{e:.0f} s | {km:.1f} km flown")

    # ---------------- PLOT ----------------
    fig, axes = plt.subplots(1, 3, figsize=(21, 7.2))
    th = np.linspace(0, 2 * np.pi, 200)
    for ax, (key, title) in zip(axes, SCEN):
        drones, shared, _, _ = results[key]
        ax.fill(JAMMER[0] + TRUE_RADIUS * np.cos(th), JAMMER[1] + TRUE_RADIUS * np.sin(th),
                color="#cf222e", alpha=0.10, zorder=1)
        ax.plot(JAMMER[0] + TRUE_RADIUS * np.cos(th), JAMMER[1] + TRUE_RADIUS * np.sin(th),
                color="#cf222e", ls="--", lw=1, zorder=1, label="Real GPS-dead zone (unknown to drones)")
        ax.scatter(*JAMMER, marker="X", s=140, color="black", zorder=6, label="Hidden jammer")
        if key != "today":
            masks = [shared.mask] if shared else [d.threat.mask for d in drones if d.threat.version]
            for m in masks:
                ax.contour(PGE, PGN, m.astype(float), levels=[0.5], colors="#e8710a", linewidths=1.8, zorder=2)
            ax.plot([], [], color="#e8710a", lw=1.8, label="Danger map estimated by drones")
        for d in drones:
            h = np.array(d.hist); ok = np.array(d.hist_gps)
            ax.plot(h[:, 0], h[:, 1], color=d.color, lw=2.2, zorder=4, label=d.name)
            bad = h.copy(); bad[ok] = np.nan
            ax.plot(bad[:, 0], bad[:, 1], color="#cf222e", lw=3, ls=":", zorder=5)
            ax.scatter(*h[0], s=60, color=d.color, zorder=6)
            if d.mode == "down":
                ax.scatter(*h[-1], marker="v", s=180, color="#cf222e", edgecolor="black", zorder=7)
        ax.plot([], [], color="#cf222e", lw=3, ls=":", label="Flying without GPS")
        ax.scatter(*TARGET, marker="*", s=420, color="gold", edgecolor="black", zorder=7, label="Target")
        r, b, e, km = summary(drones)
        detail = (f"{3 - r} drones lost inside the jammed area" if key == "today"
                  else f"{b:.0f} s without GPS  ·  done after {e:.0f} s  ·  {km:.1f} km")
        ax.set_title(f"{title}\nreached target {r}/3  ·  {detail}", fontsize=13,
                     color="#cf222e" if r < 3 else ("#1a7f37" if key == "swarm" else "black"))
        ax.set_xlim(*AREA_E); ax.set_ylim(*AREA_N); ax.set_aspect("equal")
        ax.set_xlabel("East (m)"); ax.grid(alpha=0.25)
    axes[0].set_ylabel("North (m)")
    axes[2].legend(loc="lower right", fontsize=8.5, framealpha=0.95)
    fig.suptitle("When one drone is jammed, the whole swarm learns: DETECT → LOCATE → SHARE → REROUTE",
                 fontsize=16, weight="bold")
    plt.tight_layout()
    plt.savefig("swarm_reroute.png", dpi=110)
    print("\nSaved swarm_reroute.png")

    if "--gif" in sys.argv:
        from matplotlib.animation import FuncAnimation, PillowWriter
        drones, shared, snaps, log = results["swarm"]
        fig2, ax = plt.subplots(figsize=(11, 7.5))
        ax.fill(JAMMER[0] + TRUE_RADIUS * np.cos(th), JAMMER[1] + TRUE_RADIUS * np.sin(th),
                color="#cf222e", alpha=0.08)
        ax.scatter(*JAMMER, marker="X", s=120, color="black", alpha=0.5)
        ax.scatter(*TARGET, marker="*", s=420, color="gold", edgecolor="black", zorder=7)
        danger = ax.imshow(np.zeros(PGE.shape), extent=(PE[0], PE[-1], PN[0], PN[-1]), origin="lower",
                           cmap="Oranges", vmin=0, vmax=2.5, alpha=0.55, zorder=1)
        trails = [ax.plot([], [], color=d.color, lw=2.2, label=d.name)[0] for d in drones]
        dots = [ax.plot([], [], "o", color=d.color, ms=11, mec="black")[0] for d in drones]
        clock = ax.text(0.02, 0.97, "", transform=ax.transAxes, va="top", fontsize=13, weight="bold")
        news = ax.text(0.02, 0.03, "", transform=ax.transAxes, va="bottom", fontsize=9.5, family="monospace",
                       bbox=dict(fc="white", ec="#999999", alpha=0.9))
        ax.set_xlim(*AREA_E); ax.set_ylim(*AREA_N); ax.set_aspect("equal"); ax.grid(alpha=0.2)
        ax.legend(loc="upper right", fontsize=9)
        ax.set_title("Swarm shares the danger map: only the scout loses GPS", fontsize=14, weight="bold")
        events = [(float(line.split("s")[0][2:]), line) for line in log]
        n_steps = len(snaps)

        def frame(k):
            for d, tr, dot in zip(drones, trails, dots):
                h = np.array(d.hist[:k + 1])
                tr.set_data(h[:, 0], h[:, 1]); dot.set_data([h[-1, 0]], [h[-1, 1]])
                dot.set_markerfacecolor(d.color if d.hist_gps[min(k, len(d.hist_gps) - 1)] else "#cf222e")
            if snaps[min(k, n_steps - 1)] is not None:
                danger.set_data(snaps[min(k, n_steps - 1)].astype(float))
            clock.set_text(f"t = {k * DT:.0f} s")
            recent = [line for tt, line in events if tt <= k * DT][-4:]
            news.set_text("\n".join(r[:95] for r in recent))
            return trails + dots + [danger, clock, news]

        anim = FuncAnimation(fig2, frame, frames=range(0, n_steps, 4))
        anim.save("swarm_reroute.gif", writer=PillowWriter(fps=12), dpi=70)
        print("Saved swarm_reroute.gif")
