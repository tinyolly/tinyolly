"""TinyOlly MCP server: read-only telemetry tools for AI agents.

Talks to the TinyOlly UI/API (default http://localhost:5005). Telemetry only: no config or
admin operations. Every tool returns compact, bounded output so large traces, log floods and
long metric series never blow up the agent's context. Drill down instead:

    search_traces -> get_trace (summary) -> get_trace_spans (page) -> get_span (one span, full detail)

Run:  python server.py                       (stdio, for Claude Code / Zed)
      python server.py --http [--port 8765]  (streamable HTTP)
Env:  TINYOLLY_URL (default http://localhost:5005), TINYOLLY_MCP_MAX_CHARS (default 20000)
"""

import argparse
import json
import os
import time
from collections import defaultdict
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("TINYOLLY_URL", "http://localhost:5005").rstrip("/")
MAX_CHARS = int(os.environ.get("TINYOLLY_MCP_MAX_CHARS", "20000"))
ATTR_VALUE_MAX = 200   # truncate individual attribute values / log bodies

mcp = MCPServer(
    "tinyolly",
    instructions=(
        "Read-only access to local TinyOlly telemetry (traces, spans, logs, metrics, service "
        "catalog/map). Outputs are bounded. For big traces start with get_trace (summary), then "
        "get_trace_spans with offset/limit, then get_span for one span's full attributes."
    ),
)


# ---------- helpers ----------

def _api(path: str, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    try:
        r = httpx.get(f"{BASE_URL}{path}", params=params, timeout=30)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Cannot reach TinyOlly at {BASE_URL} ({e}). Is the stack running?") from e
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _out(obj: Any) -> str:
    """Serialize compactly; hard-cap the size so a tool can never flood the context."""
    text = json.dumps(obj, separators=(",", ":"), default=str)
    if len(text) <= MAX_CHARS:
        return text
    return json.dumps(
        {"truncated": True, "total_chars": len(text), "shown_chars": MAX_CHARS,
         "hint": "Narrow the query (filters, smaller limit, offset) to see the rest.",
         "partial": text[:MAX_CHARS]})


def _fit(rows: list, overhead: int = 400) -> list:
    """Longest prefix of rows whose JSON fits the output cap, so pages are cut on row boundaries."""
    budget, used, n = MAX_CHARS - overhead, 0, 0
    for r in rows:
        used += len(json.dumps(r, separators=(",", ":"), default=str)) + 1
        if used > budget:
            break
        n += 1
    return rows[: max(n, 1)]


def _t(v: Any, n: int = ATTR_VALUE_MAX) -> Any:
    if isinstance(v, str) and len(v) > n:
        return v[:n] + f"…(+{len(v) - n} chars)"
    return v


def _attr_value(v: dict) -> Any:
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    return json.dumps(v)


def _attrs(span: dict, full: bool = False) -> dict:
    out = {}
    for a in span.get("attributes") or []:
        val = _attr_value(a.get("value", {}))
        out[a["key"]] = val if full else _t(val)
    return out


def _ms(span: dict) -> float:
    try:
        return round((int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1e6, 3)
    except (KeyError, ValueError, TypeError):
        return 0.0


def _is_error(span: dict) -> bool:
    code = (span.get("status") or {}).get("code")
    if code in (2, "STATUS_CODE_ERROR", "ERROR"):
        return True
    a = _attrs(span)
    try:
        return int(a.get("http.status_code") or a.get("http.response.status_code") or 0) >= 500
    except (TypeError, ValueError):
        return False


def _span_row(span: dict) -> dict:
    row = {
        "span_id": span.get("spanId"),
        "parent": span.get("parentSpanId") or None,
        "service": span.get("serviceName"),
        "name": _t(span.get("name"), 120),
        "kind": (span.get("kind") or "").replace("SPAN_KIND_", "").lower(),
        "ms": _ms(span),
        "error": _is_error(span),
    }
    st = (span.get("status") or {}).get("message")
    if st:
        row["status_message"] = _t(st)
    return row


# ---------- services ----------

@mcp.tool()
def list_services() -> str:
    """Service catalog with RED metrics (rate, error rate, p50/p95/p99 latency), one row per service."""
    data = _api("/api/service-catalog") or []
    rows = [{
        "service": s["name"], "spans": s.get("span_count"), "traces": s.get("trace_count"),
        "rate": s.get("rate"), "error_rate": s.get("error_rate"),
        "p50": s.get("duration_p50"), "p95": s.get("duration_p95"), "p99": s.get("duration_p99"),
    } for s in data]
    return _out(sorted(rows, key=lambda r: -(r["error_rate"] or 0)))


@mcp.tool()
def get_service_map() -> str:
    """Service dependency graph as compact edges: caller -> callee with call counts, plus node types."""
    data = _api("/api/service-map", limit=2000) or {}
    nodes = [{"id": n["id"], "type": n.get("type")} for n in data.get("nodes", [])]
    edges = [{k: e.get(k) for k in ("source", "target", "call_count", "error_count") if k in e}
             for e in data.get("edges", [])]
    return _out({"nodes": nodes, "edges": edges})


# ---------- traces ----------

@mcp.tool()
def search_traces(service: str | None = None, errors_only: bool = False,
                  min_duration_ms: float = 0, name_contains: str | None = None,
                  limit: int = 20) -> str:
    """Find recent traces (newest first). Filters: service, errors_only, min_duration_ms,
    name_contains (root span name). Returns one-line summaries; use get_trace for details."""
    limit = max(1, min(limit, 100))
    rows = _api("/api/traces", limit=5000) or []
    out = []
    for t in rows:
        if service and t.get("service_name") != service:
            continue
        if errors_only and not t.get("has_error"):
            continue
        if (t.get("duration_ms") or 0) < min_duration_ms:
            continue
        if name_contains and name_contains.lower() not in (t.get("root_span_name") or "").lower():
            continue
        out.append({
            "trace_id": t["trace_id"], "service": t.get("service_name"),
            "root": _t(t.get("root_span_name"), 100), "ms": t.get("duration_ms"),
            "spans": t.get("span_count"), "errors": t.get("error_count"),
            "start": t.get("start_time"),
        })
    out.sort(key=lambda r: -(r["start"] or 0))
    shown = _fit(out[:limit])
    return _out({"matched": len(out), "showing": len(shown), "traces": shown})


def _fetch_trace(trace_id: str) -> list[dict] | None:
    d = _api(f"/api/traces/{trace_id}")
    return None if d is None else d.get("spans", [])


@mcp.tool()
def get_trace(trace_id: str, slowest: int = 10) -> str:
    """Summary of a trace that stays small however large the trace is: duration, span/error
    counts, time and span count per service, the error spans, the slowest spans, and the
    depth/shape of the tree. Follow up with get_trace_spans (paged) or get_span (full detail)."""
    spans = _fetch_trace(trace_id)
    if spans is None:
        return _out({"error": f"trace {trace_id} not found"})
    if not spans:
        return _out({"trace_id": trace_id, "spans": 0})
    starts = [int(s["startTimeUnixNano"]) for s in spans]
    ends = [int(s["endTimeUnixNano"]) for s in spans]
    by_id = {s["spanId"]: s for s in spans}
    depth_cache: dict[str, int] = {}

    def depth(s: dict) -> int:
        sid = s["spanId"]
        if sid in depth_cache:
            return depth_cache[sid]
        d, cur, seen = 0, s, set()
        while cur.get("parentSpanId") in by_id and cur["spanId"] not in seen:
            seen.add(cur["spanId"])
            cur = by_id[cur["parentSpanId"]]
            d += 1
        depth_cache[sid] = d
        return d

    per_service: dict[str, dict] = defaultdict(lambda: {"spans": 0, "errors": 0, "self_ms": 0.0})
    for s in spans:
        p = per_service[s.get("serviceName") or "?"]
        p["spans"] += 1
        p["errors"] += _is_error(s)
        p["self_ms"] += _ms(s)
    errors = [s for s in spans if _is_error(s)]
    roots = [s for s in spans if not s.get("parentSpanId") or s["parentSpanId"] not in by_id]
    ranked = sorted(spans, key=_ms, reverse=True)[: max(1, min(slowest, 50))]
    return _out({
        "trace_id": trace_id,
        "duration_ms": round((max(ends) - min(starts)) / 1e6, 3),
        "span_count": len(spans),
        "error_count": len(errors),
        "max_depth": max(depth(s) for s in spans),
        "root_spans": [{"span_id": r["spanId"], "service": r.get("serviceName"), "name": _t(r.get("name"), 100)} for r in roots[:5]],
        "services": {k: {**v, "self_ms": round(v["self_ms"], 2)} for k, v in per_service.items()},
        "error_spans": [_span_row(s) for s in errors[:10]],
        "error_spans_omitted": max(0, len(errors) - 10),
        "slowest_spans": [_span_row(s) for s in ranked],
        "next": "get_trace_spans(trace_id, offset, limit, service?, errors_only?) to page all spans; get_span for full attributes.",
    })


@mcp.tool()
def get_trace_spans(trace_id: str, offset: int = 0, limit: int = 50, service: str | None = None,
                    errors_only: bool = False, min_duration_ms: float = 0) -> str:
    """Page through a trace's spans in start-time order (compact rows, no attributes). Handles
    traces with thousands of spans: use offset/limit and the filters. Max 200 per call."""
    spans = _fetch_trace(trace_id)
    if spans is None:
        return _out({"error": f"trace {trace_id} not found"})
    spans = sorted(spans, key=lambda s: int(s["startTimeUnixNano"]))
    if service:
        spans = [s for s in spans if s.get("serviceName") == service]
    if errors_only:
        spans = [s for s in spans if _is_error(s)]
    if min_duration_ms:
        spans = [s for s in spans if _ms(s) >= min_duration_ms]
    limit = max(1, min(limit, 200))
    page = spans[offset: offset + limit]
    t0 = int(spans[0]["startTimeUnixNano"]) if spans else 0
    rows = []
    for s in page:
        r = _span_row(s)
        r["start_ms"] = round((int(s["startTimeUnixNano"]) - t0) / 1e6, 3)
        rows.append(r)
    rows = _fit(rows)
    end = offset + len(rows)
    return _out({"total": len(spans), "offset": offset, "returned": len(rows),
                 "next_offset": end if end < len(spans) else None, "spans": rows})


@mcp.tool()
def get_span(trace_id: str, span_id: str) -> str:
    """Full detail of one span: attributes, status, events, links, resource. Long values are cut at ~2000 chars."""
    spans = _fetch_trace(trace_id)
    if spans is None:
        return _out({"error": f"trace {trace_id} not found"})
    for s in spans:
        if s.get("spanId") == span_id:
            d = _span_row(s)
            d["attributes"] = {k: _t(v, 2000) for k, v in _attrs(s, full=True).items()}
            d["resource"] = {k: _t(v, 300) for k, v in (s.get("resource") or {}).items()}
            for k in ("events", "links", "status"):
                if s.get(k):
                    d[k] = s[k]
            return _out(d)
    return _out({"error": f"span {span_id} not in trace {trace_id}"})


# ---------- logs ----------

@mcp.tool()
def query_logs(trace_id: str | None = None, service: str | None = None, severity: str | None = None,
               contains: str | None = None, limit: int = 50) -> str:
    """Recent logs (newest first), optionally by trace_id, service, severity (e.g. error, warn,
    info) or substring of the body. Bodies are truncated; max 200 rows."""
    limit = max(1, min(limit, 200))
    logs = _api("/api/logs", trace_id=trace_id, limit=5000) or []
    out = []
    for l in logs:
        if service and l.get("service_name") != service:
            continue
        if severity and (l.get("severity") or "").lower() != severity.lower():
            continue
        if contains and contains.lower() not in (l.get("message") or "").lower():
            continue
        out.append(l)
    out.sort(key=lambda l: -(l.get("timestamp") or 0))
    rows = [{"time": l.get("timestamp"), "severity": l.get("severity"), "service": l.get("service_name"),
             "message": _t(l.get("message"), 300), "trace_id": l.get("trace_id") or None,
             "span_id": l.get("span_id") or None} for l in out[:limit]]
    rows = _fit(rows)
    return _out({"matched": len(out), "returned": len(rows), "logs": rows,
                 "note": "output cap reached; narrow filters or lower limit" if len(rows) < min(limit, len(out)) else None})


# ---------- metrics ----------

@mcp.tool()
def list_metrics(search: str | None = None, limit: int = 50) -> str:
    """Available metric names (type, unit, description). `search` is a case-insensitive substring."""
    limit = max(1, min(limit, 200))
    ms = _api("/api/metrics", limit=5000) or []
    if search:
        ms = [m for m in ms if search.lower() in m["name"].lower() or search.lower() in (m.get("description") or "").lower()]
    return _out({"matched": len(ms), "metrics": [
        {"name": m["name"], "type": m.get("type"), "unit": m.get("unit"), "description": _t(m.get("description"), 100)}
        for m in ms[:limit]]})


@mcp.tool()
def query_metric(name: str, service: str | None = None, minutes: float = 10,
                 max_series: int = 10, max_points: int = 30) -> str:
    """Time series for a metric over the last `minutes`, downsampled to <= max_points per series
    (plus min/max/avg/last) and capped at max_series series. `service` filters on service.name."""
    end = time.time()
    params = {"name": name, "start": end - minutes * 60, "end": end}
    if service:
        params["resource.service.name"] = service
    d = _api("/api/metrics/query", **params)
    if not d or not d.get("series"):
        return _out({"name": name, "series": [], "note": "no data (check name with list_metrics)"})
    max_points = max(2, min(max_points, 200))
    series = []
    for s in d["series"][: max(1, min(max_series, 50))]:
        pts = [(p["timestamp"], p["value"]) for p in s.get("datapoints", []) if p.get("value") is not None]
        if not pts:
            continue
        vals = [v for _, v in pts]
        if len(pts) > max_points:
            step = len(pts) / max_points
            pts = [pts[int(i * step)] for i in range(max_points - 1)] + [pts[-1]]
        res = s.get("resource") or {}
        series.append({
            "service": res.get("service.name"),
            "resource": {k: _t(v, 60) for k, v in res.items() if k in ("service.name", "container.name", "k8s.pod.name", "host.name")},
            "attributes": s.get("attributes") or {},
            "points_total": len(vals), "min": min(vals), "max": max(vals),
            "avg": round(sum(vals) / len(vals), 6), "last": vals[-1],
            "points": [[round(t, 1), v] for t, v in pts],
        })
    return _out({"name": d.get("name"), "type": d.get("type"), "unit": d.get("unit"),
                 "series_total": len(d["series"]), "series": series})


def main() -> None:
    ap = argparse.ArgumentParser(description="TinyOlly MCP server (read-only telemetry)")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        mcp.settings.host, mcp.settings.port = a.host, a.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
