"""Turn the frames from record_mission.py into the slide-8 video.

Gazebo view full screen, our mission map as a corner window, one caption per phase,
each phase sped up to a fixed length so the whole mission fits in ~28 s.
Output: media/gazebo_mission.mp4 (1280x720, 25 fps) and media/gazebo_mission.gif
(starts with the end frame for 1.6 s, so static previews show the result).

Run: py media/make_mission_video.py
"""
import json
from datetime import datetime
from pathlib import Path

import imageio.v3 as iio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REC = HERE / "rec"
W, H, FPS = 1280, 720, 25
# phase -> (seconds in the video, caption, banner colour)
PHASES = {
    "overview": (3.0, "3 real PX4 autopilots · a GPS jammer sits on the route (the drones don't know)", (40, 60, 85)),
    "scout": (6.0, "The scout drone flies first", (40, 60, 85)),
    "jammed": (5.0, "Scout jammed → our monitor alarm · it backs out on its own breadcrumbs", (200, 40, 45)),
    "reroute": (8.0, "Danger zone shared → the other two fly around it and never lose GPS", (215, 110, 20)),
    "on_station": (3.0, "Drones arrive at the target …", (30, 140, 75)),
    "all_on_station": (4.0, "3 / 3 on station at the target · stand-off 33–38 m", (30, 140, 75)),
}
FONT = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 30)
SMALL = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
MAP_CROP = (0.0, 0.07, 0.62, 0.84)       # map axes inside the mission-app figure (fractions of width/height)


def frames(d, t0=None):
    """Map frames are named by seconds since T0; Gazebo frames by wall-clock time (2026-10-17T08:49:03.42...)."""
    files = sorted(d.glob("*.png"))
    if t0 is None:
        return np.array([float(f.stem) for f in files]), files
    ts = [datetime.strptime(f.stem[:26], "%Y-%m-%dT%H:%M:%S.%f").timestamp() - t0 for f in files]
    return np.array(ts), files


def fill(img, w, h):
    """Scale + centre-crop to exactly w x h."""
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def main():
    rec = json.loads((REC / "phases.json").read_text())
    phases = rec["phases"]
    t_gz, gz = frames(REC / "gz", rec["t0"])
    t_map, maps = frames(REC / "map")
    t_end = max(t_gz[-1], t_map[-1])
    # piecewise time map: video time -> real time
    knots_v, knots_r, segs = [0.0], [phases[0][0]], []
    for k, (t0, name) in enumerate(phases):
        t1 = phases[k + 1][0] if k + 1 < len(phases) else t_end
        dur = PHASES[name][0]
        segs.append((knots_v[-1], knots_v[-1] + dur, name, (t1 - t0) / dur))
        knots_v.append(knots_v[-1] + dur); knots_r.append(t1)
    n = int(knots_v[-1] * FPS)
    out, cache = [], {}

    def load(files, i, kind):
        key = (kind, i)
        if key not in cache:
            img = Image.open(files[i]).convert("RGB")
            if kind == "map":
                w, h = img.size
                img = img.crop((int(MAP_CROP[0] * w), int(MAP_CROP[1] * h), int(MAP_CROP[2] * w), int(MAP_CROP[3] * h)))
                img = img.resize((380, round(380 * img.height / img.width)), Image.LANCZOS)
            else:
                img = fill(img, W, H)
            cache.clear() if len(cache) > 50 else None
            cache[key] = img
        return cache[key]

    for f in range(n):
        tv = f / FPS
        tr = float(np.interp(tv, knots_v, knots_r))
        seg = next(s for s in segs if s[0] <= tv < s[1] + 1e-9)
        name, speed = seg[2], seg[3]
        # Gazebo frames arrive only every ~2 s: cross-fade between neighbours so the motion looks smooth
        i = max(int(np.searchsorted(t_gz, tr, "right")) - 1, 0)
        j = min(i + 1, len(gz) - 1)
        a = 0.0 if j == i else float(np.clip((tr - t_gz[i]) / (t_gz[j] - t_gz[i]), 0, 1))
        frame = load(gz, i, "gz") if a < 0.02 else Image.blend(load(gz, i, "gz"), load(gz, j, "gz"), a)
        frame = frame.copy()
        dr = ImageDraw.Draw(frame, "RGBA")
        # caption banner
        _, cap, col = PHASES[name]
        dr.rectangle((0, 0, W, 62), fill=col + (235,))
        dr.text((24, 15), cap, font=FONT, fill="white")
        # map corner window
        m = load(maps, max(int(np.searchsorted(t_map, tr, "right")) - 1, 0), "map")
        x0, y0 = W - m.width - 18, H - m.height - 46
        dr.rectangle((x0 - 4, y0 - 30, x0 + m.width + 4, y0 + m.height + 4), fill=(255, 255, 255, 235))
        dr.text((x0 + 4, y0 - 26), "Our mission map: where each drone thinks it is", font=SMALL, fill=(30, 30, 30))
        frame.paste(m, (x0, y0))
        # speed / clock strip
        dr.rectangle((0, H - 36, W, H), fill=(0, 0, 0, 170))
        dr.text((24, H - 30), f"real mission time {tr - phases[0][0]:4.0f} s   ·   shown ×{speed:.0f} faster   ·   "
                              "PX4 SITL + Gazebo, recorded live", font=SMALL, fill="white")
        out.append(np.asarray(frame))
    iio.imwrite(HERE / "gazebo_mission.mp4", np.stack(out), fps=FPS, codec="libx264",
                output_params=["-pix_fmt", "yuv420p", "-crf", "23"])
    # GIF: smaller, 10 fps, end frame first
    small = [np.asarray(Image.fromarray(a).resize((800, 450), Image.LANCZOS)) for a in out[::FPS // 10 + 1]]
    small = [small[-1]] * 16 + small
    iio.imwrite(HERE / "gazebo_mission.gif", np.stack(small), duration=100, loop=0)
    print(f"{n / FPS:.1f} s video, {len(small)} GIF frames")


if __name__ == "__main__":
    main()
