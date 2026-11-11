#!/usr/bin/env python3
"""Regenerate docs/images/architecture.png.

Needs matplotlib and Pillow (the MCP server's venv has both):
    docker/apps/tinyolly-mcp/.venv/bin/python scripts/make-architecture-diagram.py
Edit the BOXES / ARROWS tables below when the architecture changes. Coordinates are 0..100 (x) by 0..118 (y).
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "architecture.png"
OTEL_LOGO = mpimg.imread(ROOT / "scripts" / "assets" / "otel-logo.png")
TINY_LOGO = mpimg.imread(ROOT / "docs" / "images" / "logo.png")

NAVY, BLUE, PURPLE, GREEN, TEXT, MUTED = "#0000a0", "#0066cc", "#9b30c8", "#10a37f", "#2b2b2b", "#6b7280"
STYLE = {  # kind -> (face, edge)
    "app": ("#ffffff", BLUE),
    "otel": ("#f5f0e8", "#f5a800"),
    "tiny": ("#e8f3fc", NAVY),
    "store": ("#eefaf1", "#2e8b57"),
    "agent": ("#f1f5f9", "#475569"),
    "mcp": ("#e6f7f1", GREEN),
}

# key: (x0, y0, x1, y1, kind, title, [detail lines], logo)
BOXES = {
    "appA": (3, 99, 21, 107, "app", "App A", [], None),
    "appB": (3, 89, 21, 97, "app", "App B", [], None),
    "appC": (3, 79, 21, 87, "app", "App C", [], None),
    "collector": (33, 77, 56, 103, "otel", "OTel Collector", [":4317 gRPC · :4318 HTTP", "OpAMP supervisor", "presets applied from the UI"], "otel"),
    "receiver": (68, 77, 96, 103, "tiny", "TinyOlly OTLP Receiver", [":4343 gRPC", "traces · logs · metrics"], "tiny"),
    "sqlite": (68, 55, 96, 69, "store", "SQLite", ["embedded · compressed", "30 min TTL · 256 MB cap"], None),
    "ui": (68, 28, 96, 48, "tiny", "TinyOlly Web UI", [":5005 HTTP · REST API"], "tiny"),
    "opamp": (33, 32, 56, 50, "otel", "OpAMP Server", [":4320 WS · :4321 REST"], "otel"),
    "agents": (29, 8, 53, 20, "agent", "AI agents", ["Claude Code · Zed", "any MCP client"], None),
    "mcp": (68, 3, 96, 20, "mcp", "TinyOlly MCP Server", ["read-only: tools, charts,", "docs and investigation skills"], "tiny"),
}
# (from, to, kind, label, label offset (dx, dy), points: explicit polyline or None, both_ends)
ARROWS = [
    ((21, 93), (33, 93), BLUE, "", (0, 0), False),
    ((56, 90), (68, 90), BLUE, "OTLP", (0, 1.4), False),
    ((82, 77), (82, 69), BLUE, "", (0, 0), False),
    ((82, 55), (82, 48), BLUE, "", (0, 0), False),
    ((44.5, 77), (44.5, 50), PURPLE, "OpAMP config", (-1.0, 0), True),
    ((56, 41), (68, 41), PURPLE, "REST", (0, 1.4), True),
    ((53, 14), (68, 14), GREEN, "MCP", (0, 1.4), True),
    ((82, 20), (82, 28), GREEN, "REST API", (1.0, 0), False),
]


def draw_box(ax, key):
    x0, y0, x1, y1, kind, title, lines, logo = BOXES[key]
    face, edge = STYLE[kind]
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.6", fc=face, ec=edge, lw=2.6, zorder=2))
    cx = (x0 + x1) / 2
    y = y1 - 2.0
    if logo == "otel":                      # wide wordmark, centered above the title
        w = 19.0
        h = w * OTEL_LOGO.shape[0] / OTEL_LOGO.shape[1] * 0.78
        ax.imshow(OTEL_LOGO, extent=(cx - w / 2, cx + w / 2, y - h, y), zorder=3, aspect="auto")
        y -= h + 1.8
    elif logo == "tiny":                    # square mark, centered above the title
        s = 4.6
        ax.imshow(TINY_LOGO, extent=(cx - s / 2, cx + s / 2, y - s, y), zorder=3, aspect="auto")
        y -= s + 1.8
    if not logo:                            # no logo: centre the text block vertically
        y = (y0 + y1) / 2 + (len(lines) * 1.3 if lines else 0) + 0.2
    ax.text(cx, y, title, ha="center", va="center", fontsize=12.5 if kind == "app" else 11.5, fontweight="bold",
            color=BLUE if kind == "app" else TEXT, zorder=4)
    for i, line in enumerate(lines):
        ax.text(cx, y - 3.0 - i * 2.6, line, ha="center", va="center", fontsize=8, color=MUTED, zorder=4)


def main():
    fig, ax = plt.subplots(figsize=(9.8, 11.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(-14, 124)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.4, -13.6), 99.2, 137.2, boxstyle="round,pad=0,rounding_size=3", fc="#fafafa", ec="#d4d4d8", lw=2.5, zorder=0))

    # title
    ax.imshow(TINY_LOGO, extent=(5, 11.2, 114.6, 120.6), zorder=3, aspect="auto")
    ax.text(13.5, 118.4, "TinyOlly Architecture", ha="left", va="center", fontsize=22, fontweight="bold", color=NAVY)
    ax.text(13.6, 114.8, "Desktop OpenTelemetry observability platform, with an MCP server for AI agents", ha="left", va="center", fontsize=9.5, color=MUTED)

    for key in BOXES:
        draw_box(ax, key)
    ax.text(3, 108.8, "APPS", ha="left", va="bottom", fontsize=8.5, color=MUTED)

    for (x0, y0), (x1, y1), color, label, (dx, dy), both in ARROWS:
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="<|-|>" if both else "-|>", mutation_scale=17, lw=3.0, color=color,
                                     shrinkA=0, shrinkB=0, zorder=5))
        if label:
            ax.text((x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy, label, ha="center" if dx == 0 else ("left" if dx > 0 else "right"),
                    va="bottom" if dy else "center", fontsize=8.5, color=color, fontweight="bold", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.15", fc="#fafafa", ec="none"))

    # legend
    for i, (color, text) in enumerate([(BLUE, "Telemetry data flow"), (PURPLE, "OpAMP collector config"), (GREEN, "Query (REST / MCP)")]):
        y = -4.0 - i * 3.6
        ax.add_patch(FancyArrowPatch((4, y), (10, y), arrowstyle="-|>", mutation_scale=14, lw=3.0, color=color, shrinkA=0, shrinkB=0))
        ax.text(12, y, text, ha="left", va="center", fontsize=10.5, color=TEXT)

    fig.savefig(OUT, dpi=100, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
