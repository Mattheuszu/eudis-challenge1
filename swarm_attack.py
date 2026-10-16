"""Can an attacker trick the swarm with fake reports?  (EUDIS Hackathon 2026)

Guled's question: if drones share threat information, an enemy can broadcast a
fake message ("the jammer is in the north, go south") and steer the swarm into
a trap. Signatures stop outsiders, but not a CAPTURED drone that still has a
valid key. Here "Drone 4 (captured)" flies over the real jammer and reports
"all quiet here", pretending the jammer is 1.5 km further north.

Our defences (see swarm_reroute.py):
  1. Drones share MEASUREMENTS, never commands - nobody can order "fly east".
  2. A warning is cheap to believe, an "all clear" must be proven: a sender claiming
     "almost quiet" where another drone REALLY lost GPS is exposed as a liar.
  3. Consistency check: a sender is rejected when its readings can't be explained by
     the same jammer physics as the other drones' readings (99.9 % test).
  4. Hard evidence wins: where a drone really lost GPS stays no-go whatever anyone says.

Run: python swarm_attack.py   (saves swarm_attack.png, ~40 s)
"""
import matplotlib.pyplot as plt
import numpy as np

import swarm_reroute as S

CASES = [
    ("1. No attack", dict(attack=False, defense=True)),
    ("2. Captured drone lies, no defence", dict(attack=True, defense=False)),
    ("3. Captured drone lies, consistency check on", dict(attack=True, defense=True)),
]


def main():
    results = []
    for title, kw in CASES:
        log = []
        drones, shared, _ = S.run("swarm", log, **kw)
        results.append((title, kw, drones, shared, log))
        r, b, e, km = S.summary(drones)
        trapped = [d.name for d in drones if d.blind_s > 0 and d.name != "Drone 1"]
        print(f"\n=== {title} ===")
        print("\n".join(line for line in log if "danger map updated" not in line))
        print(f"-> reached {r}/3 | {b:.0f} s without GPS | drones lured into the jammer besides the scout: "
              f"{', '.join(trapped) or 'none'} | done after {e:.0f} s")

    fig, axes = plt.subplots(1, 3, figsize=(21, 7.4))
    th = np.linspace(0, 2 * np.pi, 200)
    u = S.ATTACK_TO - S.ATTACK_FROM
    for ax, (title, kw, drones, shared, log) in zip(axes, results):
        ax.fill(S.JAMMER[0] + S.TRUE_RADIUS * np.cos(th), S.JAMMER[1] + S.TRUE_RADIUS * np.sin(th),
                color="#cf222e", alpha=0.12)
        ax.plot(S.JAMMER[0] + S.TRUE_RADIUS * np.cos(th), S.JAMMER[1] + S.TRUE_RADIUS * np.sin(th),
                color="#cf222e", ls="--", lw=1, label="Real GPS-dead zone")
        ax.scatter(*S.JAMMER, marker="X", s=140, color="black", zorder=6, label="Real jammer")
        if kw["attack"]:
            ax.plot(*np.array([S.ATTACK_FROM, S.ATTACK_FROM + u]).T, color="#6e7781", lw=2, ls="-.",
                    label="Captured drone's claimed path")
            ax.scatter(*S.FAKE_JAMMER, marker="X", s=140, color="#6e7781", zorder=6,
                       label='Where it pretends the jammer is')
        ax.contour(S.PGE, S.PGN, shared.mask.astype(float), levels=[0.5], colors="#e8710a", linewidths=1.8)
        ax.plot([], [], color="#e8710a", lw=1.8, label="Swarm's danger map")
        for d in drones:
            h = np.array(d.hist); ok = np.array(d.hist_gps)
            ax.plot(h[:, 0], h[:, 1], color=d.color, lw=2.2, zorder=4, label=d.name)
            bad = h.copy(); bad[ok] = np.nan
            ax.plot(bad[:, 0], bad[:, 1], color="#cf222e", lw=3.2, ls=":", zorder=5)
            ax.scatter(*h[0], s=60, color=d.color, zorder=6)
        ax.plot([], [], color="#cf222e", lw=3, ls=":", label="Flying without GPS")
        ax.scatter(*S.TARGET, marker="*", s=420, color="gold", edgecolor="black", zorder=7, label="Target")
        r, b, e, km = S.summary(drones)
        trapped = sum(d.blind_s > 0 for d in drones if d.name != "Drone 1")
        verdict = f"{trapped} extra drone{'s' if trapped != 1 else ''} lured into jammer" if kw["attack"] else "only the scout loses GPS"
        rej = next((line for line in log if "CONSISTENCY" in line), None)
        ax.set_title(f"{title}\nreached {r}/3 · {b:.0f} s without GPS · {verdict}", fontsize=12.5,
                     color="#cf222e" if kw["attack"] and not kw["defense"] else ("#1a7f37" if kw["defense"] and kw["attack"] else "black"))
        if rej:
            when = rej.split("s", 1)[0].replace("t=", "").strip()
            why = rej.split(" - ", 1)[1]
            ax.text(0.02, 0.02, f"REJECTED at t = {when} s: Drone 4 (captured)\n{why[:58]}\n{why[58:116]}",
                    transform=ax.transAxes,
                    fontsize=9, family="monospace", bbox=dict(fc="white", ec="#1a7f37"))
        ax.set_xlim(*S.AREA_E); ax.set_ylim(*S.AREA_N); ax.set_aspect("equal")
        ax.set_xlabel("East (m)"); ax.grid(alpha=0.25)
    axes[0].set_ylabel("North (m)")
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, fontsize=9.5, framealpha=0.95)
    fig.suptitle("Fake reports from a captured drone: share measurements, never commands - and check them against physics",
                 fontsize=15, weight="bold")
    plt.tight_layout(rect=(0, 0.08, 1, 1))
    plt.savefig("swarm_attack.png", dpi=110)
    print("\nSaved swarm_attack.png")


if __name__ == "__main__":
    main()
