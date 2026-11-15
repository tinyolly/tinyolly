"""Presentation helpers for the TinyOlly MCP server: markdown tables, a text trace waterfall, and PNG charts.

Everything here is pure (data in, text/PNG bytes out) and bounded, so it is unit-testable without a running stack.
Charts use matplotlib's Agg backend (no display needed).
"""
import io
import time
from collections import defaultdict
from typing import Any

HEALTH = ((5, "🔴"), (0.0001, "🟡"))   # error_rate % thresholds
SEVERITY_ICON = {"error": "🔴", "fatal": "🔴", "critical": "🔴", "warn": "🟡", "warning": "🟡", "info": "🔵", "debug": "⚪", "trace": "⚪"}
COLOR_OK, COLOR_WARN, COLOR_ERR, COLOR_IDLE = "#2563eb", "#f59e0b", "#ef4444", "#94a3b8"


# ---------- small formatters ----------

def fmt_ms(ms: Any) -> str:
    try:
        n = float(ms)
    except (TypeError, ValueError):
        return "-"
    if n < 1:
        return f"{n * 1000:.0f}µs" if n else "0"
    if n < 1000:
        return f"{n:.3g}ms"
    if n < 60000:
        return f"{n / 1000:.2f}s"
    if n < 3600000:
        return f"{n / 60000:.1f}m"
    return f"{n / 3600000:.1f}h"


def fmt_time(ts: Any) -> str:
    """Seconds (float) or nanoseconds (int) since epoch -> HH:MM:SS.mmm (local time)."""
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return "-"
    if t > 1e17:
        t /= 1e9
    elif t > 1e14:
        t /= 1e6
    lt = time.localtime(t)
    return time.strftime("%H:%M:%S", lt) + f".{int((t % 1) * 1000):03d}"


def health_icon(error_rate: Any) -> str:
    try:
        e = float(error_rate or 0)
    except (TypeError, ValueError):
        return "⚪"
    for limit, icon in HEALTH:
        if e >= limit:
            return icon
    return "🟢"


def _cell(v: Any, width: int) -> str:
    s = "" if v is None else str(v).replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= width else s[: width - 1] + "…"


def md_table(headers: list[str], rows: list[list[Any]], widths: list[int] | None = None, right: set[int] | None = None) -> str:
    """GitHub markdown table; cells truncated to `widths` so one huge value cannot wreck the layout."""
    widths = widths or [60] * len(headers)
    right = right or set()
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join((" ---:" if i in right else " :---") + " " for i in range(len(headers))) + "|"
    body = ["| " + " | ".join(_cell(c, widths[i]) for i, c in enumerate(r)) + " |" for r in rows]
    return "\n".join([head, sep, *body])


# ---------- tables ----------

def catalog_table(services: list[dict]) -> str:
    rows = [[health_icon(s.get("error_rate")), s.get("name"), f"{s.get('rate', 0):g}/s", f"{s.get('error_rate', 0):g}%",
             fmt_ms(s.get("duration_p50")), fmt_ms(s.get("duration_p95")), fmt_ms(s.get("duration_p99")),
             s.get("span_count"), s.get("trace_count")] for s in services]
    return md_table(["", "Service", "Rate", "Errors", "P50", "P95", "P99", "Spans", "Traces"], rows,
                    [2, 40, 10, 9, 9, 9, 9, 8, 8], right={2, 3, 4, 5, 6, 7, 8})


def traces_table(traces: list[dict]) -> str:
    rows = [["🔴" if t.get("has_error") else "🟢", fmt_time(t.get("start_time")), t.get("service_name"), t.get("root_span_name"),
             fmt_ms(t.get("duration_ms")), t.get("span_count"), t.get("error_count"), t.get("trace_id")] for t in traces]
    return md_table(["", "Start", "Service", "Root span", "Duration", "Spans", "Errors", "Trace id"], rows,
                    [2, 12, 28, 40, 10, 6, 6, 32], right={4, 5, 6})


def spans_table(spans: list[dict]) -> str:
    rows = []
    for s in spans:
        code = str(s.get("status_code") or "")
        bad = code.startswith(("4", "5")) or (s.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR")
        rows.append(["🔴" if bad else "🟢", fmt_time(s.get("start_time")), s.get("service_name"), s.get("name"),
                     s.get("method") or "", code, fmt_ms(s.get("duration_ms")), s.get("span_id"), s.get("trace_id")])
    return md_table(["", "Start", "Service", "Name", "Method", "Status", "Duration", "Span id", "Trace id"], rows,
                    [2, 12, 28, 40, 7, 6, 10, 16, 32], right={6})


def logs_table(logs: list[dict]) -> str:
    rows = [[SEVERITY_ICON.get(str(entry.get("severity") or "").lower(), "⚪"), fmt_time(entry.get("timestamp")), entry.get("severity"),
             entry.get("service_name"), entry.get("message"), entry.get("trace_id") or ""] for entry in logs]
    return md_table(["", "Time", "Level", "Service", "Message", "Trace id"], rows, [2, 12, 8, 24, 90, 32])


# ---------- trace waterfall (text) ----------

def _span_ms(s: dict) -> float:
    try:
        return (int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6
    except (KeyError, TypeError, ValueError):
        return 0.0


def _is_err(s: dict) -> bool:
    if (s.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR", "ERROR"):
        return True
    for a in s.get("attributes") or []:
        if a.get("key") in ("http.status_code", "http.response.status_code"):
            v = a.get("value", {})
            try:
                return int(v.get("intValue") or v.get("stringValue") or 0) >= 500
            except (TypeError, ValueError):
                return False
    return False


def waterfall(spans: list[dict], max_rows: int = 60, bar_width: int = 36, name_width: int = 44) -> str:
    """Indented span tree with timing bars. Large traces keep every error span, then the slowest spans, up to max_rows
    (hidden ancestors are skipped, so kept spans nest under their nearest kept ancestor); the rest is summarised."""
    if not spans:
        return "(empty trace)"
    by_id = {s["spanId"]: s for s in spans}
    children: dict[str | None, list[dict]] = defaultdict(list)
    for s in spans:
        p = s.get("parentSpanId")
        children[p if p in by_id else None].append(s)
    for kids in children.values():
        kids.sort(key=lambda x: int(x["startTimeUnixNano"]))
    t0 = min(int(s["startTimeUnixNano"]) for s in spans)
    t1 = max(int(s["endTimeUnixNano"]) for s in spans)
    total_ns = max(t1 - t0, 1)

    keep = {s["spanId"] for s in spans}
    if len(spans) > max_rows:
        # Every error first, then the slowest spans. Hidden ancestors are simply skipped when walking, so kept spans
        # nest under their nearest kept ancestor and no row budget is spent on connecting spans.
        priority = [s for s in spans if _is_err(s)] + sorted(spans, key=_span_ms, reverse=True)
        keep = set()
        for s in priority:
            if len(keep) >= max_rows:
                break
            keep.add(s["spanId"])

    lines, shown = [], 0

    def walk(span: dict, depth: int, hidden_under: list[int]) -> None:
        nonlocal shown
        if span["spanId"] in keep:
            shown += 1
            start = (int(span["startTimeUnixNano"]) - t0) / total_ns
            width = max(_span_ms(span) * 1e6 / total_ns, 0)
            a = min(int(start * bar_width), bar_width - 1)
            b = min(max(a + 1, int(round((start + width) * bar_width))), bar_width)
            bar = " " * a + ("█" if not _is_err(span) else "▓") * (b - a) + " " * (bar_width - b)
            label = ("  " * depth + ("└ " if depth else "") + f"{span.get('serviceName') or '?'}: {span.get('name') or ''}")
            label = label if len(label) <= name_width else label[: name_width - 1] + "…"
            err = " ✗" if _is_err(span) else ""
            lines.append(f"{label:<{name_width}} │{bar}│ {fmt_ms(_span_ms(span)):>7}{err}")
            for c in children.get(span["spanId"], []):
                walk(c, depth + 1, hidden_under)
        else:
            for c in children.get(span["spanId"], []):
                walk(c, depth, hidden_under)

    for r in children.get(None, []):
        walk(r, 0, [])
    err_total = sum(_is_err(s) for s in spans)
    head = f"Trace {spans[0].get('traceId', '')}: {fmt_ms(total_ns / 1e6)}, {len(spans)} spans, {err_total} errors, {len({s.get('serviceName') for s in spans})} services"
    foot = f"\n… {len(spans) - shown} spans hidden (showing all errors + slowest); use get_trace_spans to page through them." if shown < len(spans) else ""
    return head + "\n\n```\n" + "\n".join(lines) + "\n```" + foot


# ---------- charts (PNG) ----------

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    _plt().close(fig)
    return buf.getvalue()


def _hist_stats(h: dict) -> tuple[float | None, float | None]:
    """(mean, p95 estimate from this point's buckets) for one histogram datapoint."""
    count = h.get("count") or 0
    if not count:
        return None, None
    mean = (h.get("sum") or 0) / count
    bounds, counts = h.get("explicitBounds") or [], h.get("bucketCounts") or []
    target, acc = 0.95 * count, 0
    p95 = bounds[-1] if bounds else mean
    for i, c in enumerate(counts):
        acc += c
        if acc >= target:
            p95 = bounds[i] if i < len(bounds) else (bounds[-1] if bounds else mean)
            break
    return mean, p95


def _series_labels(series: list[dict]) -> list[str]:
    """Label each series by service plus the resource/attribute keys whose values differ between series."""
    flat = []
    for s in series:
        d = {f"r.{k}": v for k, v in (s.get("resource") or {}).items()}
        d.update({k: v for k, v in (s.get("attributes") or {}).items()})
        flat.append(d)
    keys = sorted({k for d in flat for k in d})
    varying = [k for k in keys if len({str(d.get(k)) for d in flat}) > 1 and k not in ("r.service.instance.id", "r.host.name")]
    varying.sort(key=lambda k: (not k.startswith("r.service.name"), k.startswith("r."), -len({str(d.get(k)) for d in flat})))
    labels = []
    for i, d in enumerate(flat):
        parts = [str(d[k])[:28] for k in varying[:3] if d.get(k) is not None]
        base = d.get("r.service.name") or d.get("r.container.name") or "series"
        label = " · ".join(dict.fromkeys([str(base)] + parts))
        labels.append(label if label != "series" else f"series {i + 1}")
    return labels


def metric_chart(name: str, unit: str, mtype: str, series: list[dict], max_series: int = 8) -> bytes:
    """Line chart of a metric's series. Histograms: per-datapoint mean (solid) and p95 estimate (dashed), same colour."""
    from datetime import datetime

    import matplotlib.dates as mdates
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    palette = plt.get_cmap("tab10").colors
    labels = _series_labels(series)
    plotted = 0
    for i, s in enumerate(series[:max_series]):
        color = palette[i % len(palette)]
        pts = [p for p in (s.get("datapoints") or []) if p.get("timestamp")]
        xs = [datetime.fromtimestamp(p["timestamp"]) for p in pts]
        if mtype == "histogram":
            st = [_hist_stats(p["histogram"]) if p.get("histogram") else (None, None) for p in pts]
            means, p95s = [t[0] for t in st], [t[1] for t in st]
            if any(y is not None for y in means):
                nan = lambda ys: [float("nan") if y is None else y for y in ys]  # noqa: E731
                ax.plot(xs, nan(means), "-", color=color, linewidth=1.6, label=labels[i], marker="o", markersize=2.5)
                ax.plot(xs, nan(p95s), "--", color=color, linewidth=1.1, alpha=0.8)
                plotted += 1
        else:
            ys = [p.get("value") for p in pts]
            if any(y is not None for y in ys):
                ax.plot(xs, [float("nan") if y is None else y for y in ys], color=color, linewidth=1.6, label=labels[i],
                        marker="o", markersize=2.5)
                plotted += 1
    if not plotted:
        ax.text(0.5, 0.5, "no data points in range", ha="center", va="center", transform=ax.transAxes, color="#64748b")
    kind = f"{mtype}: mean solid, p95 dashed" if mtype == "histogram" else mtype
    ax.set_title(f"{name}  ({kind}{', ' + unit if unit else ''})", loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel(unit or "value")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.grid(True, alpha=0.25)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    if plotted:
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    fig.autofmt_xdate()
    return _png(fig)


def _node_color(m: dict, isolated: bool = False) -> str:
    e = float((m or {}).get("error_rate") or 0)
    if e > 5:
        return COLOR_ERR
    if e > 1:
        return COLOR_WARN
    return COLOR_IDLE if isolated else COLOR_OK


ROW = 1.35   # vertical spacing between nodes in the map charts


def node_roles(graph: dict) -> dict:
    """Same rules as the web UI's service map: shape says what the node is, colour says its health."""
    ins: dict[str, int] = defaultdict(int)
    outs: dict[str, int] = defaultdict(int)
    for e in graph.get("edges", []):
        outs[e["source"]] += 1
        ins[e["target"]] += 1
    roles = {}
    for n in graph.get("nodes", []):
        i, o = ins[n["id"]], outs[n["id"]]
        if n.get("role") in ("waypoint", "gateway", "ztunnel"):
            roles[n["id"]] = n["role"]
        elif n.get("type") == "database":
            roles[n["id"]] = "database"
        elif n.get("type") == "messaging":
            roles[n["id"]] = "messaging"
        elif i == 0 and o == 0:
            roles[n["id"]] = "isolated"
        elif i == 0:
            roles[n["id"]] = "client"
        elif o == 0:
            roles[n["id"]] = "external"
        else:
            roles[n["id"]] = "server"
    return roles


CARD_W, CARD_H = 3.6, 0.95   # node cards: name and stats live inside, so edges and labels never cross text
COL_X = 5.8                  # column pitch
INK, MUTED, LINE = "#0f172a", "#64748b", "#cbd5e1"


def _draw_node(ax, x: float, y: float, name: str, m: dict, role: str, center: bool = False) -> None:
    """Card at (x, y): role icon, service name, error/p95 line, and a stripe on the left coloured by health."""
    from matplotlib.patches import FancyBboxPatch
    color = _node_color(m, isolated=role == "isolated")
    x0, y0 = x - CARD_W / 2, y - CARD_H / 2
    ax.add_patch(FancyBboxPatch((x0, y0), CARD_W, CARD_H, boxstyle="round,pad=0,rounding_size=0.18", fc="white",
                                ec=INK if center else LINE, lw=2.6 if center else 1.2, zorder=3))
    ax.add_patch(FancyBboxPatch((x0, y0), 0.2, CARD_H, boxstyle="round,pad=0,rounding_size=0.1", fc=color, ec="none", zorder=4))
    _draw_node_icon(ax, x0 + 0.62, y, role)
    ax.text(x0 + 1.05, y + 0.17, name if len(name) <= 22 else name[:21] + "…", ha="left", va="center", fontsize=10.5,
            fontweight="bold", color=INK, zorder=5)
    ax.text(x0 + 1.05, y - 0.2, f"{m.get('error_rate', 0):g}% err · p95 {fmt_ms(m.get('duration_p95'))}", ha="left", va="center",
            fontsize=8.5, color=MUTED, zorder=5)


LEGEND_COL = 4.6   # horizontal spacing between legend items (data units)
LEGEND_ROW = 0.62


def _legend_rows(mesh: bool) -> list[list[tuple]]:
    rows: list[list[tuple]] = [[("role", "client", "client (no callers)"), ("role", "server", "service"),
                                ("role", "external", "leaf (no callees)")],
                               [("role", "isolated", "no connections")] + ([("role", "waypoint", "waypoint / ztunnel"), ("role", "gateway", "gateway")] if mesh else []),
                               [("node", COLOR_OK, "node: healthy"), ("node", COLOR_WARN, "node: >1% errors"), ("node", COLOR_ERR, "node: >5% errors")]]
    if mesh:
        rows.append([("edge", ("#16a34a", "-"), "edge: mTLS"), ("edge", ("#f59e0b", "--"), "edge: plaintext"),
                     ("edge", ("#ef4444", "-"), "edge: denied / errors")])
        rows.append([("edge", ("#94a3b8", "-"), "edge: mTLS unknown (traces only)")])
    return rows


def legend_height(mesh: bool) -> float:
    return LEGEND_ROW * len(_legend_rows(mesh)) + 0.5


def _legend(ax, x: float, y: float, mesh: bool = False) -> None:
    """Shapes = role, node colour = health, edge colour = mesh security. Rows go downward from y."""
    from matplotlib.patches import Rectangle
    for ri, items in enumerate(_legend_rows(mesh)):
        yy = y - ri * LEGEND_ROW
        for i, (kind, key, text) in enumerate(items):
            xx = x + i * LEGEND_COL
            if kind == "role":
                _draw_node_icon(ax, xx, yy, key)
            elif kind == "node":
                ax.add_patch(Rectangle((xx - 0.2, yy - 0.13), 0.4, 0.26, fc=key, ec="none", zorder=3))
            else:
                ax.plot([xx - 0.22, xx + 0.22], [yy, yy], color=key[0], linestyle=key[1], lw=2.4)
            ax.text(xx + 0.42, yy, text, fontsize=10, va="center", color="#475569")


def _finalize(fig, ax, scale: float = 0.9) -> None:
    """Size the figure to the axes' data extents so one data unit is the same length in x and y: shapes keep their proportions."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    top = 0.94
    fig.set_size_inches((x1 - x0) * scale, (y1 - y0) * scale / top)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=top)


def _draw_node_icon(ax, x: float, y: float, role: str) -> None:
    """Small role glyph (shape = role; health is the card stripe)."""
    from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle
    kw = dict(fc="#475569" if role != "isolated" else "#94a3b8", ec="none", zorder=5)
    r = 0.2
    if role == "client":
        ax.add_patch(Polygon([(x - r, y), (x, y + r), (x + r, y), (x, y - r)], **kw))
    elif role == "external":
        ax.add_patch(Polygon([(x - r, y), (x - r / 2, y + r * 0.87), (x + r / 2, y + r * 0.87), (x + r, y), (x + r / 2, y - r * 0.87), (x - r / 2, y - r * 0.87)], **kw))
    elif role == "isolated":
        ax.add_patch(Ellipse((x, y), 2 * r, 2 * r, **kw))
    elif role in ("waypoint", "ztunnel"):
        c = r * 0.5
        ax.add_patch(Polygon([(x - r + c, y + r), (x + r - c, y + r), (x + r, y + r - c), (x + r, y - r + c),
                              (x + r - c, y - r), (x - r + c, y - r), (x - r, y - r + c), (x - r, y + r - c)], **kw))
    elif role == "gateway":
        ax.add_patch(Polygon([(x - r, y + r * 0.2), (x, y + r * 1.1), (x + r, y + r * 0.2), (x + r * 0.65, y - r), (x - r * 0.65, y - r)], **kw))
    elif role == "database":
        ax.add_patch(Rectangle((x - r * 0.8, y - r), r * 1.6, r * 2, **kw))
    elif role == "messaging":
        ax.add_patch(Polygon([(x - r + 0.08, y + r * 0.8), (x + r + 0.08, y + r * 0.8), (x + r - 0.08, y - r * 0.8), (x - r - 0.08, y - r * 0.8)], **kw))
    else:
        ax.add_patch(FancyBboxPatch((x - r, y - r * 0.8), 2 * r, 1.6 * r, boxstyle="round,pad=0,rounding_size=0.05", **kw))


def edge_style(e: dict) -> tuple[str, str]:
    """(colour, linestyle) for an edge: denied red, plaintext orange dashed, errors red, mTLS green, else grey."""
    if (e.get("denied_count") or 0) > 0:
        return "#ef4444", "-"
    if e.get("mtls") is False:
        return "#f59e0b", "--"
    if (e.get("error_count") or 0) > 0:
        return "#ef4444", "-"
    if e.get("mtls") is True:
        return "#16a34a", "-"
    return "#94a3b8", "-"


def posture_line(graph: dict) -> str:
    """'mTLS 92% · 3 plaintext · 1 denied' from the edges' mesh fields, or '' when the graph has no mesh data."""
    edges = graph.get("edges") or []
    mtls = sum(1 for e in edges if e.get("mtls") is True)
    plain = sum(1 for e in edges if e.get("mtls") is False)
    denied = sum(1 for e in edges if (e.get("denied_count") or 0) > 0)
    if not (mtls or plain):
        return ""
    return f"mTLS {mtls / (mtls + plain) * 100:.0f}% · {plain} plaintext · {denied} denied"


def _draw_edge(ax, e: dict, pos: dict, t: float = 0.55, label: bool = True) -> None:
    (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
    color, style = edge_style(e)
    ax.annotate("", xy=(x2 - CARD_W / 2 - 0.06, y2), xytext=(x1 + CARD_W / 2 + 0.06, y1), zorder=1,
                arrowprops=dict(arrowstyle="-|>", color=color, linestyle=style,
                                lw=1.4 + min(2.0, (e.get("value") or e.get("call_count") or 0) ** 0.25 / 3),
                                connectionstyle="arc3,rad=0.05", shrinkA=0, shrinkB=0))
    if label and e.get("p95"):                         # metric-only edges have no latency; skip the "0" label
        label = fmt_ms(e.get("p95")) + (f" · {e['req_rate']:g}/s" if e.get("req_rate") else "")
        xs, xe = x1 + CARD_W / 2 + 0.06, x2 - CARD_W / 2 - 0.06      # label along the visible part of the edge, never on a card
        ax.text(xs + (xe - xs) * t, y1 + (y2 - y1) * t + 0.12, label, ha="center", va="bottom", fontsize=9, color="#475569", zorder=5,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#e2e8f0", lw=0.6))


def ego_graph(graph: dict, service: str, depth: int = 1, max_per_column: int = 10) -> dict:
    """Neighbourhood of one service: columns of callers (negative) and callees (positive) up to `depth` hops."""
    edges = graph.get("edges") or []
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    col = {service: 0}
    for direction in (-1, 1):
        frontier = {service}
        for d in range(1, depth + 1):
            nxt = set()
            for e in edges:
                src, dst = e["source"], e["target"]
                if direction == 1 and src in frontier and dst not in col:
                    nxt.add(dst)
                if direction == -1 and dst in frontier and src not in col:
                    nxt.add(src)
            for n in nxt:
                col[n] = direction * d
            frontier = nxt
    by_col: dict[int, list[str]] = defaultdict(list)
    for n, c in col.items():
        by_col[c].append(n)
    hidden = {}
    for c, names in by_col.items():
        names.sort(key=lambda n: -float(((nodes.get(n) or {}).get("metrics") or {}).get("span_count") or 0))
        if len(names) > max_per_column:
            hidden[c] = len(names) - max_per_column
            by_col[c] = names[:max_per_column]
    shown = {n for names in by_col.values() for n in names}
    return {"nodes": nodes, "columns": dict(by_col), "hidden": hidden,
            "edges": [e for e in edges if e["source"] in shown and e["target"] in shown
                      and col.get(e["target"], -99) == col.get(e["source"], -99) + 1]}   # only edges that run caller -> callee, left to right


def service_map_chart(graph: dict, service: str, depth: int = 1) -> bytes:
    """Callers -> service -> callees diagram for one service, nodes coloured by health, edges labelled with p95."""
    plt = _plt()
    g = ego_graph(graph, service, depth)
    cols = sorted(g["columns"])
    roles = node_roles(graph)
    mesh = bool(posture_line(graph))
    xr = max((len(cols) - 1) * COL_X + CARD_W / 2 + 0.4, 2 * LEGEND_COL + 4.0)
    # figure size proportional to the data extents so shapes keep their aspect ratio
    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor("#f8fafc")
    ax.axis("off")
    pos: dict[str, tuple[float, float]] = {}
    for ci, c in enumerate(cols):
        names = g["columns"][c]
        for ri, n in enumerate(names):
            pos[n] = (ci * COL_X, -(ri - (len(names) - 1) / 2) * ROW)
    for i, e in enumerate(g["edges"]):
        _draw_edge(ax, e, pos, 0.25 + 0.17 * (i % 4))
    for n, (x, y) in pos.items():
        _draw_node(ax, x, y, n, (g["nodes"].get(n) or {}).get("metrics") or {}, roles.get(n, "server"), center=n == service)
    for c, k in g["hidden"].items():
        x = cols.index(c) * COL_X
        ax.text(x, min(y for (px, y) in pos.values() if px == x) - 0.75, f"+{k} more", ha="center", fontsize=10, color="#64748b")
    ax.set_xlim(-CARD_W / 2 - 0.4, xr)
    ys = [y for _, y in pos.values()]
    _legend(ax, -CARD_W / 2 - 0.1, min(ys) - 1.3, mesh)
    ax.set_ylim(min(ys) - 1.3 - legend_height(mesh), max(ys) + 1.0)
    titles = {-2: "callers (2 hops)", -1: "callers", 0: "service", 1: "callees", 2: "callees (2 hops)"}
    for ci, c in enumerate(cols):
        ax.text(ci * COL_X, max(ys) + 0.75, titles.get(c, f"hop {c}"), ha="center", fontsize=10, color="#94a3b8")
    ax.set_title(f"{service}: dependencies", loc="left", fontsize=14, fontweight="bold")
    _finalize(fig, ax)
    return _png(fig)


def full_map_chart(graph: dict) -> bytes:
    """Whole service map: connected services in left-to-right layers (callers -> callees), unconnected ones in a compact grid below."""
    plt = _plt()
    roles = node_roles(graph)
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = [e for e in graph.get("edges", []) if e["source"] in nodes and e["target"] in nodes and e["source"] != e["target"]]
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    # Layers = longest path from the roots after dropping back edges (found by DFS), so every caller sits left of its callees
    # and no edge runs inside a column. Back edges (cycles such as waypoint <-> frontend) are drawn as curves.
    callees: dict[str, list[str]] = defaultdict(list)
    called = set()
    for e in edges:
        callees[e["source"]].append(e["target"])
        called.add(e["target"])
    roots = sorted(n for n in linked if n not in called)
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()

    def dfs(u: str) -> None:
        state[u] = 1
        for v in sorted(callees[u]):
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2

    for root in roots + sorted(linked - set(roots), key=lambda n: -len(callees[n])):
        if root not in state:
            dfs(root)
    preds: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if (e["source"], e["target"]) not in back:
            preds[e["target"]].append(e["source"])
    layer: dict[str, int] = {}

    def depth(n: str) -> int:
        if n not in layer:
            layer[n] = 0 if not preds[n] else 1 + max(depth(q) for q in preds[n])
        return layer[n]

    for n in linked:
        depth(n)
    def spans(n: str) -> float:
        return float(((nodes.get(n) or {}).get("metrics") or {}).get("span_count") or 0)

    by_layer: dict[int, list[str]] = defaultdict(list)
    for n, lay in layer.items():
        by_layer[lay].append(n)
    X = COL_X
    rank = {n: float(i) for names in by_layer.values() for i, n in enumerate(sorted(names, key=lambda n: -spans(n)))}
    for sweep in range(4):                              # barycentre ordering: put nodes near their neighbours to cut crossings
        order = sorted(by_layer) if sweep % 2 == 0 else sorted(by_layer, reverse=True)
        fwd = sweep % 2 == 0
        for lay in order:
            def bary(n, fwd=fwd):
                nb = [rank[e["source"] if fwd else e["target"]] for e in edges
                      if (e["target"] if fwd else e["source"]) == n]
                return sum(nb) / len(nb) if nb else rank[n]
            for i, n in enumerate(sorted(by_layer[lay], key=lambda n: (bary(n), -spans(n)))):
                rank[n] = float(i)
    pos: dict[str, tuple[float, float]] = {}
    for lay, names in by_layer.items():
        names.sort(key=lambda n: rank[n])
        for i, n in enumerate(names):
            pos[n] = (lay * X, -(i - (len(names) - 1) / 2) * ROW)
    ncols = (max(by_layer) + 1) if by_layer else 1
    rows = max((len(v) for v in by_layer.values()), default=1)
    alone = sorted((n for n in nodes if n not in linked), key=lambda n: -spans(n))
    per_row = 4
    alone_cols = min(per_row, len(alone))
    width_units = max(ncols, alone_cols, 3)             # width of the drawing in column units
    top = (rows - 1) * ROW / 2
    strip_top = -(rows - 1) * ROW / 2 - 2.9 if linked else top
    for i, n in enumerate(alone):
        pos[n] = ((i % per_row) * X * 0.75, strip_top - (i // per_row) * ROW)
    alone_rows = (len(alone) + per_row - 1) // per_row
    fig, ax = plt.subplots(figsize=(2.9 * width_units + 0.8, 1.05 * (rows + alone_rows) + 3.0))
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f8fafc")
    ax.axis("off")
    # a dense map: label only the busiest edges so the labels stay readable (the per-service chart labels all of them)
    busiest = {id(e) for e in sorted(edges, key=lambda e: -(e.get('value') or 0))[:6]}
    for i, e in enumerate(edges):
        _draw_edge(ax, e, pos, 0.25 + 0.17 * (i % 4), label=id(e) in busiest)
    for n, (x, y) in pos.items():
        _draw_node(ax, x, y, n, (nodes.get(n) or {}).get("metrics") or {}, roles.get(n, "server"))
    ys = [y for _, y in pos.values()] or [0]
    xs = [x for x, _ in pos.values()] or [0]
    if linked:
        ax.text(-CARD_W / 2, top + 1.0, "CALLERS  →  CALLEES", ha="left", fontsize=9, color="#94a3b8", fontweight="bold")
    if alone and linked:
        ax.plot([-CARD_W / 2 - 0.2, max(max(xs), (width_units - 1) * X) + 0.9], [strip_top + 1.2, strip_top + 1.2], color="#e2e8f0", lw=1, zorder=0)
        ax.text(-CARD_W / 2, strip_top + 1.4, "NO CONNECTIONS", ha="left", fontsize=9, color="#94a3b8", fontweight="bold")
    right = max(max(xs), (width_units - 1) * X) + CARD_W / 2 + 0.4
    mesh = bool(posture_line(graph))
    right = max(right, 2 * LEGEND_COL + 3.0)
    _legend(ax, -CARD_W / 2 - 0.1, min(ys) - 1.25, mesh)
    ax.set_xlim(-CARD_W / 2 - 0.4, right)
    ax.set_ylim(min(ys) - 1.25 - legend_height(mesh), max(ys) + 1.35)
    errs = sum(1 for n in nodes.values() if float(((n.get("metrics") or {}).get("error_rate")) or 0) > 5)
    ax.set_title(f"Service map  ·  {len(nodes)} services  ·  {len(edges)} connections" + (f"  ·  {errs} unhealthy" if errs else "")
                 + (f"  ·  {posture_line(graph)}" if mesh else ""),
                 loc="left", fontsize=15, fontweight="bold", color="#0f172a", pad=14)
    _finalize(fig, ax)
    return _png(fig)
