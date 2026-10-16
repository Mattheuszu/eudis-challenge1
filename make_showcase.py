"""Build SHOWCASE_standalone.html: SHOWCASE.html with every picture embedded inside it.

Some browsers block pictures when an HTML file is opened straight from disk.
The standalone file has no separate picture files, so it opens anywhere and
can be sent to someone as one file.

Run: python make_showcase.py   (after changing SHOWCASE.html or any picture)
"""
import base64
import re
from pathlib import Path

HERE = Path(__file__).parent
TYPES = {".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg"}


def embed(match):
    src = match.group(1)
    path = HERE / src
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'src="data:{TYPES[path.suffix.lower()]};base64,{data}"'


html = (HERE / "SHOWCASE.html").read_text(encoding="utf-8")
html, n = re.subn(r'src="([^":]+\.(?:png|gif|jpg))"', embed, html)
out = HERE / "SHOWCASE_standalone.html"
out.write_text(html, encoding="utf-8")
print(f"Embedded {n} pictures -> {out.name} ({out.stat().st_size / 1e6:.1f} MB)")
