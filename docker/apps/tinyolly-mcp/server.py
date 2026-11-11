"""TinyOlly MCP server: read-only telemetry tools for AI agents.

Talks to the TinyOlly UI/API (default http://localhost:5005). Telemetry only: no config or
admin operations. Every tool returns compact, bounded output so large traces, log floods and
long metric series never blow up the agent's context. Drill down instead:

    search_traces -> get_trace (summary) -> get_trace_spans (page) -> get_span (one span, full detail)

Run:  python server.py                       (stdio, for Claude Code / Zed)
      python server.py --http [--port 8765]  (streamable HTTP)
Env:  TINYOLLY_URL (default http://localhost:5005), TINYOLLY_MCP_MAX_CHARS (default 20000),
      TINYOLLY_DOCS_DIR (default <repo>/docs: the docs served by list_docs / search_docs / read_doc),
      TINYOLLY_SKILLS_DIR (default ./skills: investigation skills served by list_skills / get_skill, MCP prompts and resources)
"""

import argparse
import json
import os
import time
from collections import defaultdict
from typing import Any

import httpx
from mcp.server.mcpserver import Image, MCPServer

import docsindex
import render
import skillsindex

BASE_URL = os.environ.get("TINYOLLY_URL", "http://localhost:5005").rstrip("/")
MAX_CHARS = int(os.environ.get("TINYOLLY_MCP_MAX_CHARS", "20000"))
ATTR_VALUE_MAX = 200   # truncate individual attribute values / log bodies

DOCS = docsindex.load(docsindex.default_docs_dir())
SKILLS = skillsindex.load(skillsindex.default_skills_dir())

mcp = MCPServer(
    "tinyolly",
    instructions=(
        "Read-only access to local TinyOlly telemetry (traces, spans, logs, metrics, service "
        "catalog/map). Outputs are bounded. For big traces start with get_trace (summary), then "
        "get_trace_spans with offset/limit, then get_span for one span's full attributes. For how to set up, "
        "configure or use TinyOlly itself, use search_docs / read_doc. For investigations (what is wrong, slow or "
        "failing, one trace, one service, metrics, a broken stack) call list_skills first and follow get_skill(name)."
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
def list_services(format: str = "json") -> str:
    """Service catalog with RED metrics (rate, error rate, p50/p95/p99 latency), one row per service, worst
    errors first. format="table" returns a pretty markdown table (with health icons) to show the user."""
    data = _api("/api/service-catalog") or []
    if format == "table":
        data = sorted(data, key=lambda s: -(s.get("error_rate") or 0))
        return render.catalog_table(data[:200]) if data else "No services yet."
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
                  limit: int = 20, format: str = "json") -> str:
    """Find recent traces (newest first). Filters: service, errors_only, min_duration_ms,
    name_contains (root span name). Returns one-line summaries; use get_trace for details.
    format="table" returns a pretty markdown table to show the user."""
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
    if format == "table":
        wanted = {r["trace_id"] for r in out[:limit]}
        picked = sorted((t for t in rows if t["trace_id"] in wanted), key=lambda t: -(t.get("start_time") or 0))
        return (render.traces_table(picked) + f"\n\n{len(out)} matching traces, showing {len(picked)}.") if picked else "No matching traces."
    shown = _fit(out[:limit])
    return _out({"matched": len(out), "showing": len(shown), "traces": shown})


def _fetch_trace(trace_id: str) -> list[dict] | None:
    d = _api(f"/api/traces/{trace_id}")
    return None if d is None else d.get("spans", [])


@mcp.tool()
def get_trace(trace_id: str, slowest: int = 10, format: str = "json", max_rows: int = 60) -> str:
    """Summary of a trace that stays small however large the trace is: duration, span/error
    counts, time and span count per service, the error spans, the slowest spans, and the
    depth/shape of the tree. Follow up with get_trace_spans (paged) or get_span (full detail).
    format="waterfall" returns a text waterfall (indented span tree with timing bars) to show the user; for
    large traces it keeps all error spans and the slowest ones, up to max_rows (<=150)."""
    spans = _fetch_trace(trace_id)
    if spans is None:
        return _out({"error": f"trace {trace_id} not found"})
    if format == "waterfall":
        return render.waterfall(spans, max_rows=max(5, min(max_rows, 150)))
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
               contains: str | None = None, limit: int = 50, format: str = "json") -> str:
    """Recent logs (newest first), optionally by trace_id, service, severity (e.g. error, warn,
    info) or substring of the body. Bodies are truncated; max 200 rows.
    format="table" returns a pretty markdown table (severity icons) to show the user."""
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
    if format == "table":
        return (render.logs_table(out[:limit]) + f"\n\n{len(out)} matching logs, showing {min(limit, len(out))}.") if out else "No matching logs."
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


# ---------- spans, visuals ----------

@mcp.tool()
def search_spans(service: str | None = None, errors_only: bool = False, min_duration_ms: float = 0,
                 name_contains: str | None = None, limit: int = 30, format: str = "json") -> str:
    """Recent spans across all traces (newest first), filtered by service, errors_only, min_duration_ms or name.
    format="table" returns a pretty markdown table to show the user. Use get_span for a span's full attributes."""
    limit = max(1, min(limit, 200))
    rows = _api("/api/spans", limit=5000, service=service) or []
    out = []
    for s in rows:
        code = str(s.get("status_code") or "")
        bad = code.startswith(("4", "5")) or (s.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR")
        if errors_only and not bad:
            continue
        if (s.get("duration_ms") or 0) < min_duration_ms:
            continue
        if name_contains and name_contains.lower() not in (s.get("name") or "").lower():
            continue
        out.append(s)
    out.sort(key=lambda s: -(s.get("start_time") or 0))
    if format == "table":
        return (render.spans_table(out[:limit]) + f"\n\n{len(out)} matching spans, showing {min(limit, len(out))}.") if out else "No matching spans."
    rows = _fit([{"span_id": s["span_id"], "trace_id": s["trace_id"], "service": s.get("service_name"), "name": _t(s.get("name"), 100),
                  "ms": s.get("duration_ms"), "status": s.get("status_code") or None, "start": s.get("start_time")} for s in out[:limit]])
    return _out({"matched": len(out), "returned": len(rows), "spans": rows})


def _image_result(png: bytes, caption: str):
    return [Image(data=png, format="png"), caption]


@mcp.tool()
def chart_metric(name: str, service: str | None = None, minutes: float = 15, max_series: int = 6):
    """Line chart (PNG image) of one metric over the last `minutes`. Gauges and sums plot their value;
    histograms plot per-datapoint mean and a p95 estimate. `service` filters on service.name; at most
    max_series lines are drawn (<=12). Use list_metrics to find names."""
    end = time.time()
    params = {"name": name, "start": end - minutes * 60, "end": end}
    if service:
        params["resource.service.name"] = service
    d = _api("/api/metrics/query", **params)
    if not d or not d.get("series"):
        return f"No data for metric '{name}'" + (f" and service '{service}'" if service else "") + ". Check names with list_metrics."
    series = [s for s in d["series"] if s.get("datapoints")]
    shown = max(1, min(max_series, 12))
    png = render.metric_chart(name, d.get("unit") or "", d.get("type") or "", series, shown)
    note = f"; showing {shown} of {len(series)}" if len(series) > shown else ""
    return _image_result(png, f"{name} ({d.get('type')}, {d.get('unit') or 'no unit'}), last {minutes:g} min, {len(series)} series{note}.")


@mcp.tool()
def chart_service_map(service: str, depth: int = 1):
    """Diagram (PNG image) of one service's dependencies: callers on the left, callees on the right, nodes
    coloured by health (blue ok, amber some errors, red >5% errors), edges labelled with p95 latency and request
    rate. depth=2 adds callers/callees of those. Use list_services for names."""
    graph = _api("/api/service-map", limit=2000) or {}
    names = {n["id"] for n in graph.get("nodes", [])}
    if service not in names:
        return _out({"error": f"service '{service}' not in the service map", "available": sorted(names)[:50]})
    g = render.ego_graph(graph, service, max(1, min(depth, 2)))
    png = render.service_map_chart(graph, service, max(1, min(depth, 2)))
    callers = sum(len(v) for c, v in g["columns"].items() if c < 0)
    callees = sum(len(v) for c, v in g["columns"].items() if c > 0)
    return _image_result(png, f"{service}: {callers} callers, {callees} callees (depth {max(1, min(depth, 2))}).")


# ---------- documentation ----------

def _no_docs() -> str:
    return _out({"error": "TinyOlly docs not found. Set TINYOLLY_DOCS_DIR to the repo's docs/ directory."})


@mcp.tool()
def list_docs() -> str:
    """TinyOlly's documentation pages: name, title, description and section headings. Use read_doc(name)
    or search_docs(query) to get the content."""
    if not DOCS:
        return _no_docs()
    return _out([{"name": d.name, "title": d.title, "description": d.description,
                  "sections": [s.slug for s in d.sections if s.level in (2, 3)][:30]} for d in DOCS.values()])


@mcp.tool()
def search_docs(query: str, limit: int = 8) -> str:
    """Search the docs for words (setup, collector presets, ports, scripts, errors...). Returns the best
    matching sections with a snippet; pass doc + section to read_doc for the full text."""
    if not DOCS:
        return _no_docs()
    hits = docsindex.search(DOCS, query, max(1, min(limit, 20)))
    return _out({"query": query, "results": [{k: h[k] for k in ("doc", "section", "heading", "snippet")} for h in hits]})


@mcp.tool()
def read_doc(name: str, section: str | None = None, offset: int = 0) -> str:
    """Read a docs page (name from list_docs, e.g. "docker", "otel-demo"), optionally only one section
    (heading text or slug). Long pages are paged: pass the returned next_offset as offset."""
    if not DOCS:
        return _no_docs()
    doc = DOCS.get(name.lower().removesuffix(".md"))
    if not doc:
        return _out({"error": f"no doc '{name}'", "available": list(DOCS)})
    if section:
        found = docsindex.find_section(doc, section)
        if not found:
            return _out({"error": f"no section '{section}' in {doc.name}", "sections": [s.slug for s in doc.sections]})
        text = "\n\n".join(s.body for s in found)
    else:
        text = doc.text
    budget = MAX_CHARS - 400
    chunk = text[offset: offset + budget]
    end = offset + len(chunk)
    return _out({"doc": doc.name, "title": doc.title, "section": section, "total_chars": len(text), "offset": offset,
                 "next_offset": end if end < len(text) else None, "markdown": chunk})


@mcp.resource("tinyolly-docs://{name}", name="tinyolly-docs", mime_type="text/markdown",
              description="A TinyOlly documentation page (see list_docs for names)")
def doc_resource(name: str) -> str:
    doc = DOCS.get(name.lower().removesuffix(".md"))
    return doc.text if doc else f"No doc '{name}'. Available: {', '.join(DOCS)}"


# ---------- investigation skills: served only through the MCP server (tools, prompts, resources) ----------

@mcp.tool()
def list_skills() -> str:
    """Investigation skills for TinyOlly: step-by-step playbooks (triage, trace investigation, service deep dive,
    metrics exploration, stack troubleshooting, demo failure injection). Read one with get_skill(name)
    before starting an investigation."""
    if not SKILLS:
        return _out({"error": "no skills found (TINYOLLY_SKILLS_DIR)"})
    return _out([{"name": k.name, "when_to_use": k.description} for k in SKILLS.values()])


def _skill(name: str):
    return SKILLS.get(name) or SKILLS.get(f"tinyolly-{name}")


@mcp.tool()
def get_skill(name: str) -> str:
    """The full text of one investigation skill (name from list_skills). Follow its steps."""
    k = _skill(name)
    if not k:
        return _out({"error": f"no skill '{name}'", "available": list(SKILLS)})
    return k.body


@mcp.resource("tinyolly-skills://{name}", name="tinyolly-skills", mime_type="text/markdown",
              description="A TinyOlly investigation skill (see list_skills for names)")
def skill_resource(name: str) -> str:
    k = _skill(name)
    return k.body if k else f"No skill '{name}'. Available: {', '.join(SKILLS)}"


def _register_skill_prompts() -> None:
    """One MCP prompt per skill, so clients with a prompt picker (slash commands) can start an investigation."""
    for skill in SKILLS.values():
        def make(sk=skill):
            def prompt(focus: str = "") -> str:
                head = f"Investigate with the TinyOlly MCP tools using this skill" + (f". Focus: {focus}" if focus else ".")
                return f"{head}\n\n{sk.body}"
            return prompt
        mcp.prompt(name=skill.name, description=skill.description)(make())


_register_skill_prompts()


def main() -> None:
    ap = argparse.ArgumentParser(description="TinyOlly MCP server (read-only telemetry)")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        mcp.run(transport="streamable-http", host=a.host, port=a.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
