"""MCP server tests with a faked TinyOlly API. Run: ./run-tests.sh (or pytest tests from this directory)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

T = "ab" * 16


def span(i, parent=None, service="svc", dur_ms=10, error=False, attrs=None):
    s = {"traceId": T, "spanId": f"{i:016x}", "name": f"op-{i}", "kind": "SPAN_KIND_SERVER",
         "startTimeUnixNano": str(1_000_000_000 + i * 1_000_000),
         "endTimeUnixNano": str(1_000_000_000 + i * 1_000_000 + dur_ms * 1_000_000),
         "serviceName": service, "attributes": attrs or [], "status": {"code": 2, "message": "boom"} if error else {}}
    if parent:
        s["parentSpanId"] = f"{parent:016x}"
    return s


def big_trace(n=3000):
    return [span(i + 1, parent=(i // 2) or None, service=f"svc-{i % 5}", dur_ms=i % 50 + 1, error=(i % 400 == 7),
                 attrs=[{"key": "blob", "value": {"stringValue": "x" * 3000}}]) for i in range(n)]


@pytest.fixture
def api(monkeypatch):
    """Route server._api calls to a dict of path -> payload (or callable)."""
    routes = {}

    def fake(path, **params):
        v = routes.get(path)
        return v(**params) if callable(v) else v
    monkeypatch.setattr(server, "_api", fake)
    return routes


def call(fn, *a, **k):
    return json.loads(fn(*a, **k))


def test_get_trace_summary_is_small_for_huge_trace(api):
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": big_trace()}
    raw = len(json.dumps(api[f"/api/traces/{T}"]))
    out = server.get_trace(T)
    assert raw > 9_000_000 and len(out) < 8_000          # 9 MB trace -> a few KB
    d = json.loads(out)
    assert d["span_count"] == 3000 and d["error_count"] == 8
    assert len(d["slowest_spans"]) == 10 and len(d["error_spans"]) == 8
    assert set(d["services"]) == {f"svc-{i}" for i in range(5)}


def test_get_trace_spans_paginates_and_filters(api):
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": big_trace()}
    p1 = call(server.get_trace_spans, T, offset=0, limit=50)
    assert p1["total"] == 3000 and p1["returned"] == 50 and p1["next_offset"] == 50
    last = call(server.get_trace_spans, T, offset=2950, limit=200)
    assert last["returned"] == 50 and last["next_offset"] is None
    assert call(server.get_trace_spans, T, errors_only=True)["total"] == 8
    assert call(server.get_trace_spans, T, service="svc-1")["total"] == 600
    big = call(server.get_trace_spans, T, limit=10_000)                       # request is capped at 200 rows...
    assert 0 < big["returned"] <= 200 and big["next_offset"] == big["returned"]   # ...and cut on a row boundary
    assert all("attributes" not in s for s in p1["spans"])                    # rows stay compact


def test_get_span_full_detail_truncates_huge_values(api):
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": [span(1, attrs=[{"key": "blob", "value": {"stringValue": "x" * 9000}}])]}
    d = call(server.get_span, T, f"{1:016x}")
    assert "chars)" in d["attributes"]["blob"] and len(d["attributes"]["blob"]) < 2100
    assert "error" in call(server.get_span, T, "nope")


def test_unknown_trace(api):
    assert "not found" in call(server.get_trace, "00" * 16)["error"]


def test_output_hard_cap(monkeypatch):
    monkeypatch.setattr(server, "MAX_CHARS", 500)
    d = json.loads(server._out({"rows": ["y" * 100] * 100}))
    assert d["truncated"] is True and len(json.dumps(d)) < 1200


def test_search_traces_filters(api):
    rows = [{"trace_id": f"{i:032x}", "service_name": "a" if i % 2 else "b", "duration_ms": i, "span_count": 3,
             "error_count": i % 3 == 0, "has_error": i % 3 == 0, "root_span_name": f"GET /r{i}", "start_time": i}
            for i in range(1, 31)]
    api["/api/traces"] = rows
    assert call(server.search_traces, service="a")["matched"] == 15
    assert call(server.search_traces, errors_only=True)["matched"] == 10
    assert call(server.search_traces, min_duration_ms=25)["matched"] == 6
    d = call(server.search_traces, limit=3)
    assert d["showing"] == 3 and d["traces"][0]["start"] == 30          # newest first


def test_list_services_and_map(api):
    api["/api/service-catalog"] = [{"name": "ok", "error_rate": 0}, {"name": "bad", "error_rate": 50}]
    assert [s["service"] for s in call(server.list_services)] == ["bad", "ok"]   # worst first
    api["/api/service-map"] = {"nodes": [{"id": "a", "type": "service", "metrics": {"x": 1}}],
                               "edges": [{"source": "a", "target": "b", "call_count": 4, "junk": 1}]}
    m = call(server.get_service_map)
    assert m["nodes"] == [{"id": "a", "type": "service"}] and m["edges"] == [{"source": "a", "target": "b", "call_count": 4}]


def test_query_logs_filters_and_truncates(api):
    logs = [{"timestamp": i, "severity": "error" if i % 2 else "info", "service_name": "cart", "message": "m" * 1000 if i == 5 else f"hello {i}",
             "trace_id": "", "span_id": ""} for i in range(1, 21)]
    api["/api/logs"] = logs
    assert call(server.query_logs, severity="error")["matched"] == 10
    assert call(server.query_logs, contains="hello 7")["matched"] == 1
    d = call(server.query_logs, limit=500)
    assert d["returned"] == 20 and d["logs"][0]["time"] == 20
    assert max(len(l["message"]) for l in d["logs"]) < 340


def test_query_metric_downsamples(api):
    series = [{"resource": {"service.name": f"s{i}"}, "attributes": {},
               "datapoints": [{"timestamp": float(t), "value": float(t)} for t in range(1000)]} for i in range(30)]
    api["/api/metrics/query"] = {"name": "m", "type": "gauge", "unit": "1", "series": series}
    d = call(server.query_metric, "m", max_series=5, max_points=20)
    assert d["series_total"] == 30 and len(d["series"]) == 5
    s = d["series"][0]
    assert len(s["points"]) == 20 and s["points_total"] == 1000 and (s["min"], s["max"], s["last"]) == (0, 999, 999)
    assert s["points"][-1][1] == 999                                     # last point kept


def test_query_metric_empty(api):
    api["/api/metrics/query"] = {"name": "x", "series": []}
    assert call(server.query_metric, "x")["series"] == []


def test_list_metrics_search(api):
    api["/api/metrics"] = [{"name": "container.cpu", "type": "sum"}, {"name": "http.duration", "description": "CPU time"},
                           {"name": "memory", "type": "gauge"}]
    assert call(server.list_metrics, search="cpu")["matched"] == 2


def test_unreachable_api_gives_clear_error(monkeypatch):
    monkeypatch.setattr(server, "BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="Is the stack running"):
        server._api("/api/traces")
