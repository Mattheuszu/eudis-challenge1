"""
Jammer hunter  (EUDIS Hackathon 2026)
Turns the drones from victims of jamming into sensors.

Every GPS receiver measures how much interference it hears (PX4 logs a
jamming indicator). Interference gets stronger closer to the jammer, so a
few measurements from known positions tell us where the jammer is - like
triangulating a radio. Positions come from our GPS-free navigation
(terrain matching, sim_long.py), not from the jammed GPS.

  Drone A flies the main 8.8 km route.
  Drone B flies a second route. Together they pin the jammer down.

Run: python jammer_hunt.py            (saves jammer_hunt.png and jammer_hunt.gif)
     python jammer_hunt.py --no-gif   (only the picture, faster)
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter

import sim_long as S

# ---------------- SETTINGS (play with these) ----------------
JAMMER = np.array([6200.0, 3000.0])   # m, where the enemy jammer really is (the drones don't know)
JAMMER_POWER = 77.0      # dB, jamming-to-noise at 1 m (sets how far it reaches)
SHADOWING = 3.0          # dB, random variation from hills, trees, multipath
GPS_LOST_DB = 15.0       # above this the GPS stops working -> red zone
FLY_HEIGHT = 120.0       # m above ground
READ_EVERY = 10.0        # s, one reading per 10 s (closer readings share the same errors)
GRID = 50.0              # m, search grid for the jammer position
POWERS = np.arange(60.0, 95.01, 0.25)   # dB, jammer strengths to try
SEED = 3

ROUTE_A = (S.START.copy(), S.ROUTE.copy())
ROUTE_B = (np.array([8500.0, 4200.0]),
           np.array([[6500.0, 3900.0], [4500.0, 3300.0], [2000.0, 3000.0]]))
# --------------------------------------------------------------


def jn_db(xy, jammer, power):
    """Interference level heard at positions xy (free-space: -20 dB per 10x distance)."""
    d2 = ((xy - jammer) ** 2).sum(-1) + FLY_HEIGHT**2
    return power - 10 * np.log10(d2)


def fly_route(start, route):
    """Fly a route with GPS-free navigation (terrain matching in snow)."""
    S.START, S.ROUTE, S.DESTINATION = start, route, route[-1]
    return S.fly(use_terrain=True, weather="snow")


def heard(jn):
    """What the receiver reports: total noise level above its normal floor (dB).
    Far from the jammer this is ~0 dB, close to it, it is the jamming level."""
    return 10 * np.log10(1 + 10 ** (jn / 10))


def measure(log, rng):
    """Every READ_EVERY s: noise level, tagged with where the drone THINKS it is."""
    step = int(READ_EVERY / S.DT)
    true = log["true"][::step]
    est = np.array(log["est"])[::step]
    level = heard(jn_db(true, JAMMER, JAMMER_POWER)) + rng.normal(0, SHADOWING, len(true))
    return est, level


def locate(pts, level):
    """Try every grid point and jammer strength; keep the pair that explains the
    readings best. Returns best position, its power, the grid and the 95 % area."""
    gx = np.arange(-1500, 10500, GRID)
    gy = np.arange(-2000, 5000, GRID)
    GX, GY = np.meshgrid(gx, gy)
    cand = np.stack([GX.ravel(), GY.ravel()], 1)
    sse = np.full(len(cand), np.inf)
    power = np.zeros(len(cand))
    for i in range(0, len(cand), 2000):
        c = cand[i:i + 2000]
        fall = -10 * np.log10(((pts[None] - c[:, None]) ** 2).sum(-1) + FLY_HEIGHT**2)
        for p in POWERS:
            s = ((level - heard(p + fall)) ** 2).sum(axis=1)
            better = s < sse[i:i + 2000]
            sse[i:i + 2000][better] = s[better]
            power[i:i + 2000][better] = p
    k = sse.argmin()
    region = ((sse - sse[k]) / SHADOWING**2 < 5.99).reshape(GX.shape)  # 95 % confidence
    return cand[k], power[k], GX, GY, region


def red_zone_radius(power):
    """Distance (along the ground) inside which GPS is lost."""
    return np.sqrt(max(10 ** ((power - GPS_LOST_DB) / 10) - FLY_HEIGHT**2, 0))


def main():
    # ---------------- RUN ----------------
    rng = np.random.default_rng(SEED)
    print("Flying drone A (main route) and drone B (second route) without GPS ...")
    log_a = fly_route(*ROUTE_A)
    log_b = fly_route(*ROUTE_B)
    S.START, S.ROUTE, S.DESTINATION = ROUTE_A[0], ROUTE_A[1], ROUTE_A[1][-1]

    pts_a, jn_a = measure(log_a, rng)
    pts_b, jn_b = measure(log_b, rng)
    est_a, pow_a, GX, GY, reg_a = locate(pts_a, jn_a)
    est_ab, pow_ab, _, _, reg_ab = locate(np.vstack([pts_a, pts_b]), np.concatenate([jn_a, jn_b]))

    cell_km2 = GRID**2 / 1e6
    true_r = red_zone_radius(JAMMER_POWER)
    print(f"\nTrue jammer at {JAMMER.round()}, GPS lost within {true_r:.0f} m")
    print(f"{'':22s} {'measurements':>12s} {'error':>8s} {'95% area':>10s} {'red zone':>9s}")
    for name, n, est, pw, reg in [("Drone A alone", len(jn_a), est_a, pow_a, reg_a),
                                  ("Drones A + B", len(jn_a) + len(jn_b), est_ab, pow_ab, reg_ab)]:
        err = np.linalg.norm(est - JAMMER)
        print(f"{name:22s} {n:12d} {err:6.0f} m {reg.sum() * cell_km2:7.2f} km2 {red_zone_radius(pw):7.0f} m")

    # ---------------- PLOT ----------------
    fig = plt.figure(figsize=(20, 8))
    ax3 = fig.add_axes([0.0, 0.02, 0.52, 0.86], projection="3d", computed_zorder=False)
    ax2 = fig.add_axes([0.57, 0.1, 0.36, 0.75])

    # 3D: terrain, paths, estimated red zone
    gx3 = np.linspace(-500, 9000, 160)
    gy3 = np.linspace(-1500, 4500, 100)
    X3, Y3 = np.meshgrid(gx3, gy3)
    Z3 = S.terrain(X3, Y3)
    ax3.plot_surface(X3, Y3, Z3, cmap="bone", vmin=Z3.min() - 40, vmax=Z3.max(),
                     linewidth=0, antialiased=False, alpha=0.95, zorder=1)


    def above(xy):
        return S.terrain(xy[:, 0], xy[:, 1]) + FLY_HEIGHT


    r_est = red_zone_radius(pow_ab)
    th = np.linspace(0, 2 * np.pi, 60)
    ring = est_ab + np.stack([np.cos(th), np.sin(th)], 1) * r_est
    zr = np.linspace(Z3.min(), Z3.max() + FLY_HEIGHT + 80, 2)
    TH, ZR = np.meshgrid(th, zr)
    ax3.plot_surface(est_ab[0] + r_est * np.cos(TH), est_ab[1] + r_est * np.sin(TH), ZR,
                     color="#cf222e", alpha=0.18, linewidth=0, zorder=3)
    ax3.plot(ring[:, 0], ring[:, 1], S.terrain(ring[:, 0], ring[:, 1]) + 3, color="#cf222e", lw=2, zorder=4)

    for log, color, label in [(log_a, "#2a6fdb", "Drone A"), (log_b, "#8a63d2", "Drone B")]:
        p = log["true"][::5]
        ax3.plot(p[:, 0], p[:, 1], above(p), color=color, lw=2.5, label=label, zorder=6)
    ax3.scatter(*JAMMER, S.terrain(*JAMMER) + 10, s=120, marker="X", color="black", zorder=8,
                depthshade=False, label="Real jammer (hidden)")
    ax3.scatter(*est_ab, S.terrain(*est_ab) + 10, s=160, marker="^", color="#cf222e", zorder=9,
                depthshade=False, label="Estimated jammer")
    ax3.set_box_aspect((9.5, 6.0, 1.6), zoom=1.1)
    ax3.view_init(elev=38, azim=-62)
    ax3.set_xlabel("East (m)", labelpad=12); ax3.set_ylabel("North (m)", labelpad=8)
    ax3.set_zlabel("Height (m)")
    ax3.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax3.set_title("Threat map shared with every drone: red = GPS lost here", fontsize=13)

    # 2D: what the drones heard and how sure we are
    field = jn_db(np.stack([GX, GY], -1), JAMMER, JAMMER_POWER)
    ax2.contourf(GX, GY, np.clip(field, 0, None), levels=15, cmap="Reds", alpha=0.35)
    sc = ax2.scatter(np.vstack([pts_a, pts_b])[:, 0], np.vstack([pts_a, pts_b])[:, 1],
                     c=np.concatenate([jn_a, jn_b]), cmap="magma_r", s=10, label="Measurements")
    fig.colorbar(sc, cax=fig.add_axes([0.945, 0.15, 0.012, 0.65]), label="Interference heard (dB)")
    ax2.contour(GX, GY, reg_a.astype(float), levels=[0.5], colors="#e8710a", linewidths=2)
    ax2.contour(GX, GY, reg_ab.astype(float), levels=[0.5], colors="#cf222e", linewidths=2.5)
    ax2.plot([], [], color="#e8710a", lw=2, label=f"Drone A alone: 95% area ({reg_a.sum() * cell_km2:.2f} km²)")
    ax2.plot([], [], color="#cf222e", lw=2.5, label=f"Drones A + B: 95% area ({reg_ab.sum() * cell_km2:.2f} km²)")
    ax2.scatter(*JAMMER, s=150, marker="X", color="black", zorder=5, label="Real jammer")
    ax2.scatter(*est_a, s=110, marker="^", color="#e8710a", edgecolor="black", zorder=5,
                label=f"Estimate, A alone: {np.linalg.norm(est_a - JAMMER):.0f} m off")
    ax2.scatter(*est_ab, s=150, marker="^", color="#cf222e", edgecolor="black", zorder=6,
                label=f"Estimate, A + B: {np.linalg.norm(est_ab - JAMMER):.0f} m off")
    ax2.set_xlim(-500, 9500); ax2.set_ylim(-1500, 5000)
    ax2.set_aspect("equal")
    ax2.set_xlabel("East (m)"); ax2.set_ylabel("North (m)")
    ax2.set_title("Where is the jammer? (top view)", fontsize=13)
    ax2.legend(loc="lower right", fontsize=9, framealpha=0.95)

    fig.suptitle(f"Jammer hunter: two drones without GPS locate the jammer to within "
                 f"{np.linalg.norm(est_ab - JAMMER):.0f} m", fontsize=15, weight="bold")
    plt.savefig("jammer_hunt.png", dpi=110)
    print("\nSaved jammer_hunt.png")

    if "--no-gif" not in sys.argv:
        print("Writing jammer_hunt.gif (rotating view) ...")
        frames = 48
        anim = FuncAnimation(fig, lambda i: ax3.view_init(elev=38, azim=-62 + 360 * i / frames), frames=frames)
        anim.save("jammer_hunt.gif", writer=PillowWriter(fps=12), dpi=60)
        print("Saved jammer_hunt.gif")


if __name__ == "__main__":
    main()
