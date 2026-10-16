"""Export swarm_reroute.py runs as compact JSON for the radar web page."""
import json

import numpy as np

import swarm_reroute as S

CELL = 250.0   # m, size of an interference-report cell (like public jamming maps)


def export(scenario):
    log = []
    drones, shared, snaps = S.run(scenario, log)
    n = max(len(d.hist) for d in drones)
    out = {"drones": [], "events": [], "masks": [], "cells": []}
    for d in drones:
        h = np.array(d.hist)
        g = np.array(d.hist_gps)
        out["drones"].append({
            "name": d.name, "color": d.color, "depart": d.depart,
            "x": np.round(h[:, 0]).astype(int).tolist(), "y": np.round(h[:, 1]).astype(int).tolist(),
            "gps": g.astype(int).tolist(), "arrived": d.arrived, "down": d.mode == "down",
        })
    for line in log:
        t = float(line.split("s", 1)[0].replace("t=", "").strip())
        out["events"].append([t, line.split("s  ", 1)[1]])
    # danger map: keep only the snapshots where it changed
    if scenario == "swarm":
        last = None
        for k, m in enumerate(snaps):
            if m is None:
                continue
            key = m.tobytes()
            if key != last:
                rows = ["".join("1" if v else "0" for v in row) for row in m]
                out["masks"].append({"t": k * S.DT, "rows": rows})
                last = key
    # interference reports: every 4 s each flying drone reports what it hears (dB above noise)
    reports = []
    for d in drones:
        h = np.array(d.hist)
        for k in range(0, len(h), 4):
            if k < d.depart or (k > 0 and np.allclose(h[k], h[k - 1]) and k > d.depart + 5):
                continue
            level = float(S.heard(S.jn_db(h[k], S.JAMMER, S.JAMMER_POWER)))
            reports.append([int(h[k][0] // CELL), int(h[k][1] // CELL), round(k * S.DT), round(level, 1)])
    out["cells"] = reports            # the page keeps the loudest report per cell seen so far
    out["steps"] = n
    return out


data = {
    "area": {"e": list(S.AREA_E), "n": list(S.AREA_N), "plan_cell": S.PLAN_CELL,
             "pe0": float(S.PE[0]), "pn0": float(S.PN[0]), "cell": CELL},
    "target": S.TARGET.tolist(),
    "jammer": S.JAMMER.tolist(),
    "jam_radius": round(float(S.TRUE_RADIUS)),
    "gps_lost_db": S.GPS_LOST_DB,
    "dt": S.DT,
    "today": export("today"),
    "swarm": export("swarm"),
}
with open("radar_data.json", "w") as f:
    json.dump(data, f, separators=(",", ":"))
print("drones:", [d["name"] for d in data["swarm"]["drones"]], "| steps:", data["swarm"]["steps"],
      "| mask snapshots:", len(data["swarm"]["masks"]), "| cells:", len(data["swarm"]["cells"]))
