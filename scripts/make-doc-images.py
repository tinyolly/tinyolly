#!/usr/bin/env python3
"""Regenerate the documentation screenshots, or check that the docs use them correctly.

  scripts/make-doc-images.py                     # all shots from the running stack
  scripts/make-doc-images.py --only mesh-map-diff
  scripts/make-doc-images.py --seed              # first post a fault scenario (for the diff and trace path)
  scripts/make-doc-images.py --check             # no stack needed: files exist, previews small, links clickable

Every shot is written twice: docs/images/<name>.png (preview, at most PREVIEW_W wide, what the docs
show) and docs/images/full/<name>.png (full size, what a click opens). Docs embed a shot as
  [![alt](images/<name>.png)](images/full/<name>.png)
or, where a width is needed, <a href="../images/full/<name>.png"><img src="../images/<name>.png" width="400"></a>
Prefixes: MkDocs rewrites markdown links itself, so markdown in docs/*.md uses `images/`; raw HTML is not
rewritten and pages are served at /<page>/, so HTML there uses `../images/` (docs/index.md: `images/`). README.md
uses `docs/images/` for both.
Sources: "ui" shots are headless Chrome screenshots of a TinyOlly tab; "mcp" shots are the PNGs the
MCP chart tools return. Needs macOS Chrome (or CHROME=...) and Pillow or macOS sips for resizing.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
IMAGES = ROOT / "docs" / "images"
FULL = IMAGES / "full"
PREVIEW_W = 900
MAX_PREVIEW_BYTES = 300_000
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
TRACE_ID = "0123456789abcdef0123456789abcdef"  # the trace seed_mesh.py posts

# name, kind, args. ui: tab id. mcp: (tool, arguments).
SHOTS = [
    ("ui-logs", "ui", "logs"),
    ("ui-metrics", "ui", "metrics"),
    ("ui-traces", "ui", "traces"),
    ("ui-service-catalog", "ui", "catalog"),
    ("ui-service-map", "ui", "map"),
    ("ui-collector", "ui", "collector"),
    ("mesh-service-map", "mcp", ("chart_service_map", {})),
    ("mesh-map-diff", "mcp", ("chart_map_diff", {"minutes": 30, "window_seconds": 60})),
    ("mesh-trace-path", "mcp", ("chart_trace_path", {"trace_id": TRACE_ID})),
]
EMBED = re.compile(r"\[!\[[^\]]*\]\((?P<thumb>[^)]*images/(?P<n>[\w-]+)\.png)\)\]\((?P<full>[^)]*)\)")
BARE = re.compile(r"(?<!\[)!\[[^\]]*\]\((?:\.\./|)(?:docs/)?images/(?P<n>(?:ui|mesh)-[\w-]+)\.png\)")
HTML = re.compile(r"(?P<pre>.{0,160})<img[^>]+src=\"(?:\.\./|)(?:docs/)?images/(?P<n>(?:ui|mesh)-[\w-]+)\.png\"", re.S)


def resize(src, dst):
    try:
        from PIL import Image
        im = Image.open(src)
        if im.width > PREVIEW_W:
            im = im.resize((PREVIEW_W, round(im.height * PREVIEW_W / im.width)), Image.LANCZOS)
        im.save(dst, optimize=True)
    except ImportError:  # macOS sips; it would enlarge small images, so only shrink wide ones
        shutil.copy(src, dst)
        width = subprocess.run(["sips", "-g", "pixelWidth", str(src)], capture_output=True, text=True).stdout.split()[-1]
        if int(width) > PREVIEW_W:
            subprocess.run(["sips", "--resampleWidth", str(PREVIEW_W), str(dst)], check=True, capture_output=True)


def write_pair(name, png_bytes):
    FULL.mkdir(parents=True, exist_ok=True)
    full = FULL / f"{name}.png"
    full.write_bytes(png_bytes)
    resize(full, IMAGES / f"{name}.png")


def shoot_ui(name, tab, ui):
    tmp = Path(f"/tmp/docshot-{name}.png")
    tmp.unlink(missing_ok=True)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1500,950",
                    "--virtual-time-budget=15000", f"--screenshot={tmp}", f"{ui}/?tab={tab}"],
                   capture_output=True, timeout=90)
    if not tmp.exists():
        raise RuntimeError(f"Chrome produced no screenshot for {tab}")
    write_pair(name, tmp.read_bytes())


def shoot_mcp(name, spec, client):
    import base64
    tool, args = spec
    for item in client.call_content(tool, args):
        if item["type"] == "image":
            return write_pair(name, base64.b64decode(item["data"]))
    raise RuntimeError(f"{tool} returned no image: " + " ".join(c.get("text", "") for c in client.call_content(tool, args))[:200])


def seed(otlp, ui):
    """Baseline, then a fault with a change marker, so the diff and the trace path have something to show."""
    for scenario in ("baseline", "fault"):
        subprocess.run([sys.executable, str(HERE / "seed_mesh.py"), "--otlp", otlp, "--ui", ui, "--scenario", scenario,
                        "--interval", "5", "--duration", "75", "--trace"], check=True, capture_output=True)
    time.sleep(5)


def check():
    problems = []
    known = {n for n, *_ in SHOTS}
    for n in sorted(known):
        for p in (IMAGES / f"{n}.png", FULL / f"{n}.png"):
            if not p.exists():
                problems.append(f"missing {p.relative_to(ROOT)} (run scripts/make-doc-images.py)")
        thumb = IMAGES / f"{n}.png"
        if thumb.exists() and thumb.stat().st_size > MAX_PREVIEW_BYTES:
            problems.append(f"{thumb.relative_to(ROOT)} is {thumb.stat().st_size // 1000} KB; previews must stay under {MAX_PREVIEW_BYTES // 1000} KB")
    for doc in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        text = doc.read_text()
        for m in re.finditer(r"(?:src|href)=\"((?:\.\./|docs/)?images/(?:full/)?(?:ui|mesh)-[\w-]+\.png)\"", text):
            want = "docs/images/" if doc.name == "README.md" else "images/" if doc.name == "index.md" else "../images/"
            if not m.group(1).startswith(want):
                problems.append(f"{doc.relative_to(ROOT)}: HTML path {m.group(1)} must start with {want}")
        for m in re.finditer(r"\]\(((?:\.\./|docs/)?images/(?:full/)?(?:ui|mesh)-[\w-]+\.png)\)", text):
            want = "docs/images/" if doc.name == "README.md" else "images/"
            if not m.group(1).startswith(want):
                problems.append(f"{doc.relative_to(ROOT)}: markdown path {m.group(1)} must start with {want} (MkDocs rewrites it)")
        for m in BARE.finditer(text):
            problems.append(f"{doc.relative_to(ROOT)}: {m.group('n')} is not click-to-expand; use [![alt](images/{m.group('n')}.png)](images/full/{m.group('n')}.png)")
        for m in HTML.finditer(text):
            if f"images/full/{m.group('n')}.png" not in m.group("pre"):
                problems.append(f"{doc.relative_to(ROOT)}: <img> for {m.group('n')} must sit inside <a href=\"...images/full/{m.group('n')}.png\">")
        for m in EMBED.finditer(text):
            n = m.group("n")
            if n in known and not m.group("full").endswith(f"images/full/{n}.png"):
                problems.append(f"{doc.relative_to(ROOT)}: link for {n} should open images/full/{n}.png")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default=os.environ.get("TINYOLLY_UI", "http://localhost:5005"))
    ap.add_argument("--mcp", default=os.environ.get("TINYOLLY_MCP", "http://localhost:8765/mcp"))
    ap.add_argument("--otlp", default=os.environ.get("TINYOLLY_OTLP", "http://localhost:4318"), help="used by --seed")
    ap.add_argument("--only", action="append", help="shot name; repeatable")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        problems = check()
        print("\n".join(problems) or f"doc images OK ({len(SHOTS)} shots)")
        return 1 if problems else 0
    if args.seed:
        seed(args.otlp, args.ui)
    sys.path.insert(0, str(HERE))
    from agent_eval.mcp_client import MCPClient
    client = None
    failed = 0
    for name, kind, spec in SHOTS:
        if args.only and name not in args.only:
            continue
        try:
            if kind == "ui":
                shoot_ui(name, spec, args.ui)
            else:
                client = client or MCPClient(args.mcp)
                shoot_mcp(name, spec, client)
            print(f"ok   {name}")
        except Exception as exc:  # keep going; report at the end
            failed += 1
            print(f"FAIL {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
