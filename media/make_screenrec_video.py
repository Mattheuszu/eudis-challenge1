"""Edit Den's screen recording of the live 3-drone mission into the slide-8 video.

Layout 1920x1080: Gazebo 3D view on the left, our mission app (status banner + map) on
the right, one caption per phase, each phase sped up so the mission fits in ~29 s.
Output: media/gazebo_mission.mp4 and media/gazebo_mission.gif (GIF starts with the end
frame for 1.6 s so static previews show the result).

Run: py media/make_screenrec_video.py "<recording.mp4>"
"""
import sys
from pathlib import Path

import imageio.v3 as iio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SRC = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\den\Videos\Screen Recordings\Screen Recording 2026-10-17 093927.mp4"
W, H, FPS = 1920, 1080, 25
# crop boxes in the 3298x1206 recording (left, top, right, bottom)
GZ = (1940, 75, 2880, 1125)         # Gazebo 3D view
BANNER = (1170, 135, 1734, 270)     # mission app status banner
MAP = (135, 210, 1155, 945)         # mission app map
# (recording start, end, seconds in the video, caption, colour)
PHASES = [
    (0.0, 11.5, 4.0, "3 real PX4 autopilots take off · a GPS jammer sits on the route (the drones don't know where)", (40, 62, 90)),
    (11.5, 20.0, 5.0, "Scout jammed → our alarm in 1 s → it backs out on its own breadcrumbs", (196, 36, 44)),
    (20.0, 57.5, 9.0, "Danger zone shared → the other two fly around it and never lose GPS", (214, 108, 18)),
    (57.5, 94.0, 7.0, "Drones arrive at the target, one by one", (28, 132, 70)),
    (94.0, 100.1, 4.0, "3 / 3 on station · only the scout ever lost GPS", (28, 132, 70)),
]
BG = (14, 22, 33)
F_CAP = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 38)
F_SMALL = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 24)
F_TAG = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 24)


def wrap(text, font, width, draw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) > width and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    return lines + [cur]


def compose(src, phase, speed):
    canvas = Image.new("RGB", (W, H), BG)
    gz = Image.fromarray(src[GZ[1]:GZ[3], GZ[0]:GZ[2]])
    gz = gz.resize((round(gz.width * H / gz.height), H), Image.LANCZOS)
    canvas.paste(gz, (0, 0))
    x0 = gz.width + 40
    pw = W - x0 - 40
    d = ImageDraw.Draw(canvas)
    # caption card
    _, _, _, cap, col = phase
    lines = wrap(cap, F_CAP, pw - 50, d)
    ch = 40 + 50 * len(lines)
    d.rounded_rectangle((x0, 36, x0 + pw, 36 + ch), 18, fill=col)
    for k, line in enumerate(lines):
        d.text((x0 + 25, 56 + 50 * k), line, font=F_CAP, fill="white")
    # app banner + map
    y = 36 + ch + 30
    d.text((x0, y), "OUR MISSION APP — LIVE", font=F_TAG, fill=(147, 161, 179))
    y += 38
    ban = Image.fromarray(src[BANNER[1]:BANNER[3], BANNER[0]:BANNER[2]])
    ban = ban.resize((pw, round(ban.height * pw / ban.width)), Image.LANCZOS)
    m = Image.fromarray(src[MAP[1]:MAP[3], MAP[0]:MAP[2]])
    room = H - 70 - y - ban.height - 16
    s = min(pw / m.width, room / m.height)
    m = m.resize((round(m.width * s), round(m.height * s)), Image.LANCZOS)
    canvas.paste(ban, (x0, y))
    y += ban.height + 16
    d.rounded_rectangle((x0 - 6, y - 6, x0 + m.width + 6, y + m.height + 6), 10, fill="white")
    canvas.paste(m, (x0, y))
    # footer
    d.text((x0, H - 52), f"shown ×{speed:.0f} faster  ·  real PX4 SITL + Gazebo, recorded live", font=F_SMALL,
           fill=(147, 161, 179))
    return canvas


def write_gif(out):
    """Small GIF for the slide (autoplays in PowerPoint): 640x360, 5 fps, one shared palette."""
    small = [Image.fromarray(a).resize((640, 360), Image.LANCZOS) for a in out[::5]]
    small = [small[-1]] * 8 + small
    pal = Image.fromarray(np.vstack([np.asarray(small[k]) for k in (12, len(small) // 2, -1)])).quantize(
        colors=96, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in small]
    frames[0].save(HERE / "gazebo_mission.gif", save_all=True, append_images=frames[1:], duration=200, loop=0,
                   optimize=True)


def main():
    if "--gif-only" in sys.argv:          # re-make only the GIF from the finished MP4
        write_gif([f for f in iio.imiter(HERE / "gazebo_mission.mp4")])
        return
    meta = iio.immeta(SRC)
    src_fps = meta["fps"]
    # output frame -> wanted source time
    wanted = []
    for k, (t0, t1, dur, *_rest) in enumerate(PHASES):
        n = round(dur * FPS)
        for i in range(n):
            wanted.append((t0 + (t1 - t0) * i / n, k, (t1 - t0) / dur))
    out, j = [], 0
    for i, f in enumerate(iio.imiter(SRC)):
        t = i / src_fps
        while j < len(wanted) and wanted[j][0] <= t:
            _, k, speed = wanted[j]
            out.append(np.asarray(compose(f, PHASES[k], speed)))
            j += 1
        if j >= len(wanted):
            break
    while j < len(wanted):                       # recording ended a few frames early: hold the last one
        out.append(out[-1]); j += 1
    iio.imwrite(HERE / "gazebo_mission.mp4", np.stack(out), fps=FPS, codec="libx264",
                output_params=["-pix_fmt", "yuv420p", "-crf", "22", "-preset", "medium"])
    write_gif(out)
    print(f"{len(out) / FPS:.1f} s video, {len(frames)} GIF frames")


if __name__ == "__main__":
    main()
