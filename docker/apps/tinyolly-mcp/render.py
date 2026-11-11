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
    rows = [[SEVERITY_ICON.get(str(l.get("severity") or "").lower(), "⚪"), fmt_time(l.get("timestamp")), l.get("severity"),
             l.get("service_name"), l.get("message"), l.get("trace_id") or ""] for l in logs]
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
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
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
    import matplotlib.dates as mdates
    from datetime import datetime
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
    if e > 0:
        return COLOR_WARN
    return COLOR_IDLE if isolated else COLOR_OK


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
    from matplotlib.patches import FancyBboxPatch
    plt = _plt()
    g = ego_graph(graph, service, depth)
    cols = sorted(g["columns"])
    rows = max(len(v) for v in g["columns"].values())
    fig, ax = plt.subplots(figsize=(3.6 * len(cols) + 1, max(3.2, 0.95 * rows + 1.4)))
    ax.axis("off")
    pos: dict[str, tuple[float, float]] = {}
    for ci, c in enumerate(cols):
        names = g["columns"][c]
        for ri, n in enumerate(names):
            pos[n] = (ci * 3.4, -(ri - (len(names) - 1) / 2) * 1.0)
    for e in g["edges"]:
        (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
        ax.annotate("", xy=(x2 - 1.05, y2), xytext=(x1 + 1.05, y1),
                    arrowprops=dict(arrowstyle="-|>", color="#64748b", lw=1.1 + min(2.0, (e.get("value") or 0) ** 0.25 / 3),
                                    connectionstyle="arc3,rad=0.08"))
        label = f"{fmt_ms(e.get('p95'))} p95" + (f"\n{e.get('req_rate'):g} req/s" if e.get("req_rate") else "")
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.14, label, ha="center", va="bottom", fontsize=7, color="#475569",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    for n, (x, y) in pos.items():
        m = (g["nodes"].get(n) or {}).get("metrics") or {}
        center = n == service
        ax.add_patch(FancyBboxPatch((x - 1.0, y - 0.32), 2.0, 0.64, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc=_node_color(m), ec="#0f172a" if center else "none", lw=2.4 if center else 0, alpha=0.95))
        ax.text(x, y + 0.09, n if len(n) <= 24 else n[:23] + "…", ha="center", va="center", color="white", fontsize=9,
                fontweight="bold" if center else "normal")
        ax.text(x, y - 0.17, f"{m.get('error_rate', 0):g}% err · p95 {fmt_ms(m.get('duration_p95'))}", ha="center", va="center",
                color="white", fontsize=7)
    for c, k in g["hidden"].items():
        x = cols.index(c) * 3.4
        ax.text(x, min(y for (px, y) in pos.values() if px == x) - 0.75, f"+{k} more", ha="center", fontsize=8, color="#64748b")
    ax.set_xlim(-1.4, (len(cols) - 1) * 3.4 + 1.4)
    ys = [y for _, y in pos.values()]
    ax.set_ylim(min(ys) - 1.1, max(ys) + 1.0)
    titles = {-2: "callers (2 hops)", -1: "callers", 0: "service", 1: "callees", 2: "callees (2 hops)"}
    for ci, c in enumerate(cols):
        ax.text(ci * 3.4, max(ys) + 0.75, titles.get(c, f"hop {c}"), ha="center", fontsize=8, color="#94a3b8")
    ax.set_title(f"{service}: dependencies", loc="left", fontsize=12, fontweight="bold")
    return _png(fig)
