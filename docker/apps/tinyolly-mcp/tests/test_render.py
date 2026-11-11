"""Pretty output + charts. Run: ./run-tests.sh"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render  # noqa: E402
import server  # noqa: E402
from test_server import T, big_trace, span  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def api(monkeypatch):
    routes = {}
    monkeypatch.setattr(server, "_api", lambda path, **p: (routes.get(path)(**p) if callable(routes.get(path)) else routes.get(path)))
    return routes


def test_formatters():
    assert render.fmt_ms(0.039) == "39µs"
    assert render.fmt_ms(12.345) == "12.3ms" and render.fmt_ms(1500) == "1.50s" and render.fmt_ms(600002) == "10.0m"
    assert render.fmt_ms(None) == "-" and render.fmt_ms(0) == "0"
    assert render.health_icon(0) == "🟢" and render.health_icon(1) == "🟡" and render.health_icon(9) == "🔴"
    assert render.fmt_time(1_700_000_000.5).endswith(".500") and render.fmt_time(1_700_000_000_500_000_000).endswith(".500")


def test_md_table_truncates_and_escapes():
    t = render.md_table(["a", "b"], [["x" * 100, "p|q"]], [10, 10])
    lines = t.splitlines()
    assert len(lines) == 3 and "…" in lines[2] and "p\\|q" in lines[2] and lines[0].count("|") == 3


def test_catalog_table_worst_first_and_icons(api):
    api["/api/service-catalog"] = [{"name": "ok", "error_rate": 0, "rate": 2}, {"name": "bad", "error_rate": 50, "rate": 1, "duration_p95": 1500}]
    out = server.list_services(format="table")
    assert out.index("bad") < out.index("ok") and "🔴" in out and "🟢" in out and "1.50s" in out
    assert json.loads(server.list_services())[0]["service"] == "bad"           # default stays JSON


def test_trace_span_log_tables(api):
    api["/api/traces"] = [{"trace_id": f"{i:032x}", "service_name": "a", "root_span_name": "GET /x", "duration_ms": i, "span_count": 2,
                           "error_count": i % 2, "has_error": bool(i % 2), "start_time": i * 10**9} for i in range(1, 6)]
    out = server.search_traces(format="table", limit=3)
    assert out.splitlines()[0].startswith("| ") and "5 matching traces, showing 3" in out and "🔴" in out
    assert f"{5:032x}" in out                                                       # full trace ids: they are inputs to get_trace
    api["/api/spans"] = [{"span_id": "s1", "trace_id": "t1", "name": "GET", "duration_ms": 3, "status_code": "500", "service_name": "x", "start_time": 10**18}]
    assert "🔴" in server.search_spans(format="table") and json.loads(server.search_spans())["matched"] == 1
    assert json.loads(server.search_spans(errors_only=True))["matched"] == 1
    api["/api/logs"] = [{"timestamp": 1.7e9, "severity": "error", "service_name": "x", "message": "boom\nline2", "trace_id": "ab" * 16}]
    out = server.query_logs(format="table")
    assert "🔴" in out and "boom line2" in out


def test_waterfall_small_and_large(api):
    small = [span(1, service="a", dur_ms=50), span(2, parent=1, service="b", dur_ms=20, error=True)]
    w = render.waterfall(small)
    assert "a: op-1" in w and "└ b: op-2" in w and "✗" in w and "hidden" not in w
    big = big_trace(3000)
    w = render.waterfall(big, max_rows=40)
    rows = [l for l in w.splitlines() if "│" in l]
    assert 0 < len(rows) <= 40 and "spans hidden" in w and w.count("✗") == 8       # every error span survives
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": big}
    assert len(server.get_trace(T, format="waterfall", max_rows=30)) < 6000


def test_ego_graph_only_forward_edges():
    g = {"nodes": [{"id": n, "metrics": {"span_count": 1}} for n in "abcde"],
         "edges": [{"source": "a", "target": "c"}, {"source": "c", "target": "d"}, {"source": "d", "target": "c"}, {"source": "b", "target": "c"},
                   {"source": "c", "target": "e"}]}
    e = render.ego_graph(g, "c", depth=1)
    assert sorted(e["columns"][-1]) == ["a", "b", "d"] and e["columns"][1] == ["e"]      # d is a caller; it is not also a callee
    cols = {n: c for c, ns in e["columns"].items() for n in ns}
    assert all(cols[ed["target"]] == cols[ed["source"]] + 1 for ed in e["edges"])


def test_charts_are_png_images(api):
    now = time.time()
    api["/api/metrics/query"] = {"name": "m", "type": "histogram", "unit": "ms", "series": [
        {"resource": {"service.name": f"s{i}"}, "attributes": {"route": f"/r{i}"}, "datapoints": [
            {"timestamp": now - 60 + t, "value": 5.0, "histogram": {"count": 4, "sum": 20.0, "bucketCounts": [1, 2, 1, 0], "explicitBounds": [1.0, 5.0, 10.0]}}
            for t in range(10)]} for i in range(9)]}
    res = server.chart_metric("m", minutes=5, max_series=4)
    assert isinstance(res, list) and res[0].data[:8] == PNG and "showing 4 of 9" in res[1]
    api["/api/metrics/query"] = {"name": "g", "type": "gauge", "unit": "", "series": []}
    assert isinstance(server.chart_metric("g"), str)                             # empty -> text, not an image
    api["/api/service-map"] = {"nodes": [{"id": n, "label": n, "metrics": {"error_rate": 6 if n == "b" else 0}} for n in "abc"],
                               "edges": [{"source": "a", "target": "b", "p95": 12, "req_rate": 1.5}, {"source": "b", "target": "c", "p95": 3}]}
    res = server.chart_service_map("b", depth=2)
    assert res[0].data[:8] == PNG and "1 callers, 1 callees" in res[1]
    assert "available" in json.loads(server.chart_service_map("nope"))


def test_chart_handles_huge_neighbourhood():
    names = [f"svc-{i}" for i in range(60)]
    g = {"nodes": [{"id": n, "label": n, "metrics": {"span_count": i}} for i, n in enumerate(names)] + [{"id": "hub", "label": "hub", "metrics": {}}],
         "edges": [{"source": "hub", "target": n} for n in names]}
    png = render.service_map_chart(g, "hub")
    assert png[:8] == PNG and render.ego_graph(g, "hub")["hidden"] == {1: 50}


def test_full_map_chart_renders_connected_and_isolated():
    graph = {"nodes": [{"id": n, "metrics": {"span_count": 5}} for n in "abcde"],
             "edges": [{"source": "a", "target": "b", "p95": 12, "req_rate": 2}, {"source": "b", "target": "c"},
                       {"source": "c", "target": "a"}]}   # includes a cycle; d and e are unconnected
    png = render.full_map_chart(graph)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert render.full_map_chart({"nodes": [], "edges": []})[:4] == b"\x89PNG"
