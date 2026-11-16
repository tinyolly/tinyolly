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


def test_service_map_mesh_fields_and_posture(api):
    api["/api/service-map"] = {"nodes": [{"id": "wp", "type": "service", "role": "waypoint"}],
                               "edges": [{"source": "a", "target": "wp", "value": 9, "mtls": True, "source_kind": "metrics",
                                          "denied_count": 2, "p95": 0, "extra": 1}]}
    m = call(server.get_service_map)
    assert m["nodes"] == [{"id": "wp", "type": "service", "role": "waypoint"}]
    assert m["edges"] == [{"source": "a", "target": "wp", "value": 9, "p95": 0, "mtls": True,
                           "source_kind": "metrics", "denied_count": 2}]
    api["/api/mesh-posture"] = {"mtls_pct": 50.0, "plaintext": [], "denied": []}
    assert call(server.get_mesh_posture)["mtls_pct"] == 50.0


def test_get_service_map_filters_and_limit(api):
    api["/api/service-map"] = {"nodes": [{"id": n, "type": "service"} for n in "abcd"], "edges": [
        {"source": "a", "target": "b", "value": 5, "mtls": True},
        {"source": "b", "target": "c", "value": 9, "mtls": False},
        {"source": "c", "target": "d", "value": 1, "mtls": True, "denied_count": 3, "error_count": 1}]}
    assert [e["target"] for e in call(server.get_service_map)["edges"]] == ["c", "b", "d"]       # busiest first
    assert [e["target"] for e in call(server.get_service_map, service="b")["edges"]] == ["c", "b"]
    d = call(server.get_service_map, only="plaintext")
    assert [e["source"] for e in d["edges"]] == ["b"] and {n["id"] for n in d["nodes"]} == {"b", "c"}
    assert [e["source"] for e in call(server.get_service_map, only="denied")["edges"]] == ["c"]
    assert len(call(server.get_service_map, only="errors")["edges"]) == 1
    cut = call(server.get_service_map, limit=1)
    assert len(cut["edges"]) == 1 and cut["edges_total"] == 3


def test_find_denied_plaintext_and_get_edge(api):
    api["/api/mesh-posture"] = {"denied": [{"source": "i", "target": "cart", "count": 5}],
                                "plaintext": [{"source": "a", "target": "x", "value": 1}]}
    assert call(server.find_denied) == [{"source": "i", "target": "cart", "count": 5}]
    assert call(server.find_plaintext)[0]["target"] == "x"
    api["/api/service-map"] = {"nodes": [], "edges": [{"source": "a", "target": "b", "value": 7, "mtls": False, "error_count": 1}]}
    api["/api/service-catalog"] = [{"name": "a", "rate": 2, "error_rate": 0, "duration_p95": 3}, {"name": "b", "error_rate": 9}]
    d = call(server.get_edge, "a", "b")
    assert d["edge"]["mtls"] is False and d["source"]["rate"] == 2 and d["target"]["error_rate"] == 9
    miss = call(server.get_edge, "a", "zzz")
    assert "no edge" in miss["error"] and miss["edges_touching_these_services"] == ["a -> b"]


def test_query_logs_filters_and_truncates(api):
    logs = [{"timestamp": i, "severity": "error" if i % 2 else "info", "service_name": "cart", "message": "m" * 1000 if i == 5 else f"hello {i}",
             "trace_id": "", "span_id": ""} for i in range(1, 21)]
    api["/api/logs"] = logs
    assert call(server.query_logs, severity="error")["matched"] == 10
    assert call(server.query_logs, contains="hello 7")["matched"] == 1
    d = call(server.query_logs, limit=500)
    assert d["returned"] == 20 and d["logs"][0]["time"] == 20
    assert max(len(entry["message"]) for entry in d["logs"]) < 340


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


def test_image_result_saves_png(tmp_path):
    out = server._image_result(b"\x89PNGdata", "cap", str(tmp_path / "sub" / "m.png"))
    assert (tmp_path / "sub" / "m.png").read_bytes() == b"\x89PNGdata"
    assert "Saved to" in out[1]
    assert "Could not save" in server._image_result(b"x", "cap", "/proc/nope/x.png")[1]


def _mseries(**attrs):
    first, last = attrs.pop("first"), attrs.pop("last")
    return {"resource": {"service.name": "ztunnel"}, "attributes": attrs,
            "datapoints": [{"timestamp": 1.0, "value": first}, {"timestamp": 2.0, "value": last}]}


def test_query_metric_label_filter_is_sent_as_attribute_params(api):
    seen = {}

    def fake(**params):
        seen.update(params)
        return {"name": "m", "series": [_mseries(code="200", first=1, last=2)]}
    api["/api/metrics/query"] = fake
    call(server.query_metric, "m", labels={"response_code": "403", "reporter": "waypoint"})
    assert seen["attribute.response_code"] == "403" and seen["attribute.reporter"] == "waypoint"


def test_query_metric_group_by_sums_series_per_label_value(api):
    api["/api/metrics/query"] = {"name": "reqs", "type": "sum", "unit": "1", "series": [
        _mseries(dest="cart", code="200", first=0, last=10), _mseries(dest="cart", code="500", first=5, last=8),
        _mseries(dest="ad", code="200", first=0, last=100), _mseries(code="200", first=0, last=1)]}
    d = call(server.query_metric, "reqs", group_by="dest")
    assert d["group_by"] == "dest" and d["series_total"] == 4
    assert [g["value"] for g in d["groups"]] == ["ad", "cart", None]          # largest delta first; missing label last
    cart = d["groups"][1]
    assert cart["series_count"] == 2 and cart["last_sum"] == 18 and cart["delta_sum"] == 13
    assert "series" not in d


def test_query_metric_group_by_respects_max_series(api):
    api["/api/metrics/query"] = {"name": "m", "series": [_mseries(k=str(i), first=0, last=i) for i in range(10)]}
    d = call(server.query_metric, "m", group_by="k", max_series=3)
    assert len(d["groups"]) == 3 and d["groups_total"] == 10


NOW = 1_000_000.0           # seconds; trace start_time is in nanoseconds
MIN = 60 * 10**9


def _tr(svc, minutes_ago, ms=10, error=False):
    return {"trace_id": "t", "service_name": svc, "duration_ms": ms, "has_error": error,
            "start_time": int(NOW * 1e9 - minutes_ago * MIN)}


def test_compare_windows_flags_what_changed(api, monkeypatch):
    monkeypatch.setattr(server.time, "time", lambda: NOW)
    api["/api/traces"] = (
        [_tr("steady", 1), _tr("steady", 2), _tr("steady", 6), _tr("steady", 7)]
        + [_tr("fresh", 1)]                                                    # only in the current window
        + [_tr("dead", 7), _tr("dead", 8)]                                     # only in the previous window
        + [_tr("bad", 1, error=True), _tr("bad", 2, error=True), _tr("bad", 6), _tr("bad", 7)]
        + [_tr("slow", 1, ms=300), _tr("slow", 7, ms=100)]
        + [_tr("old", 30)])                                                    # outside both windows
    d = call(server.compare_windows, minutes=5)
    by = {s["service"]: s for s in d["services"]}
    assert d["window_minutes"] == 5 and "old" not in by
    assert by["fresh"]["change"] == "new" and by["dead"]["change"] == "gone"
    assert by["bad"]["change"] == "errors_up" and (by["bad"]["errors_now"], by["bad"]["errors_prev"]) == (2, 0)
    assert by["slow"]["change"] == "slower" and (by["slow"]["p95_now"], by["slow"]["p95_prev"]) == (300, 100)
    assert by["steady"]["change"] == "steady" and by["steady"]["traces_now"] == 2 and by["steady"]["traces_prev"] == 2
    assert d["services"][-1]["service"] == "steady"                            # changed services first


def test_compare_windows_service_filter_and_errors_down(api, monkeypatch):
    monkeypatch.setattr(server.time, "time", lambda: NOW)
    api["/api/traces"] = [_tr("a", 1), _tr("a", 7, error=True), _tr("b", 1)]
    d = call(server.compare_windows, minutes=5, service="a")
    assert [s["service"] for s in d["services"]] == ["a"] and d["services"][0]["change"] == "errors_down"


def _attr(**kv):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in kv.items()]


def _proxy(i, parent, ms, flags="-", status="200", url="http://cart:7070/Get"):
    return span(i, parent=parent, service="waypoint.shop", dur_ms=ms,
                attrs=_attr(component="proxy", response_flags=flags, **{"http.status_code": status, "http.url": url}))


def test_get_trace_mesh_computes_mesh_time_retries_and_flags(api):
    spans = [span(1, service="frontend", dur_ms=100),
             _proxy(2, 1, 40),                                   # healthy hop: 40 ms in the proxy, app took 30
             span(3, parent=2, service="cart", dur_ms=30),
             _proxy(4, 1, 5, flags="UF", status="503", url="http://pay:80/Charge"),     # failing hop, three attempts
             _proxy(5, 1, 5, flags="UF", status="503", url="http://pay:80/Charge"),
             _proxy(6, 1, 5, flags="URX,UF", status="503", url="http://pay:80/Charge")]
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": spans}
    d = call(server.get_trace_mesh, T)
    assert d["proxy_spans"] == 4 and d["total_mesh_ms"] == 25.0          # 10 (cart hop) + 5 * 3 (no app child: whole span)
    cart = next(h for h in d["hops"] if h["app_service"] == "cart")
    assert (cart["proxy_ms"], cart["app_ms"], cart["mesh_ms"], cart["attempts"]) == (40, 30, 10, 1)
    pay = [h for h in d["hops"] if h["url"] == "http://pay:80/Charge"]
    assert len(pay) == 3 and all(h["attempts"] == 3 for h in pay) and pay[0]["app_service"] is None
    assert d["retries"] == [{"url": "http://pay:80/Charge", "attempts": 3}]
    flags = {f["code"]: f["meaning"] for h in d["hops"] for f in h["flags"]}
    assert flags["UF"] == "upstream connection failure" and flags["URX"] == "retry limit exceeded"
    assert d["hops"][0]["mesh_ms"] >= d["hops"][-1]["mesh_ms"]           # biggest mesh time first


def test_get_trace_mesh_without_proxy_spans(api):
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": [span(1, service="a"), span(2, parent=1, service="b")]}
    d = call(server.get_trace_mesh, T)
    assert d["proxy_spans"] == 0 and d["hops"] == [] and "no proxy spans" in d["note"]


def _vs(version, code, first, last, svc="cart"):
    return {"resource": {"service.name": "ztunnel"},
            "attributes": {"destination_service_name": svc, "destination_version": version, "response_code": code},
            "datapoints": [{"timestamp": 1.0, "value": first}, {"timestamp": 2.0, "value": last}]}


def test_get_version_split_shares_and_error_rates(api):
    seen = {}

    def fake(**params):
        if params["name"] == "istio_requests_total":
            seen.update(params)
        return {"name": params["name"], "series": [
            _vs("v1", "200", 0, 70), _vs("v1", "500", 0, 10),          # v1: 80 requests, 10 errors
            _vs("v2", "200", 5, 25),                                   # v2: 20 requests, no errors
            _vs("", "200", 0, 0)]}                                     # no traffic: dropped
    api["/api/metrics/query"] = fake
    d = call(server.get_version_split, "cart", minutes=15)
    assert seen["name"] == "istio_requests_total" and seen["attribute.destination_canonical_service"] == "cart"
    assert d["service"] == "cart" and d["total_requests"] == 100
    v1, v2 = d["versions"]
    assert (v1["version"], v1["requests"], v1["share_pct"], v1["errors"], v1["error_rate_pct"]) == ("v1", 80, 80.0, 10, 12.5)
    assert (v2["version"], v2["requests"], v2["share_pct"], v2["errors"], v2["error_rate_pct"]) == ("v2", 20, 20.0, 0, 0.0)


def test_get_version_split_falls_back_to_service_name(api):
    calls = []

    def fake(**params):
        calls.append(params)
        if "attribute.destination_service_name" in params:
            return {"name": "istio_requests_total", "series": [_vs("v1", "200", 0, 10)]}
        return {"name": "istio_requests_total", "series": []}
    api["/api/metrics/query"] = fake
    d = call(server.get_version_split, "cart")
    assert len([c for c in calls if c["name"] == "istio_requests_total"]) == 2 and d["total_requests"] == 10


def test_get_version_split_includes_avg_latency(api):
    def hist(count, total):
        return {"count": count, "sum": total, "bucketCounts": [], "explicitBounds": []}

    def lat(version, c0, s0, c1, s1):
        return {"attributes": {"destination_version": version, "destination_canonical_service": "cart"},
                "datapoints": [{"timestamp": 1.0, "value": None, "histogram": hist(c0, s0)},
                               {"timestamp": 2.0, "value": None, "histogram": hist(c1, s1)}]}

    def fake(**params):
        if params["name"] == "istio_request_duration_milliseconds":
            return {"name": params["name"], "series": [lat("v1", 0, 0, 90, 180), lat("v2", 5, 100, 15, 4100)]}
        return {"name": "istio_requests_total", "series": [_vs("v1", "200", 0, 90), _vs("v2", "200", 0, 10)]}
    api["/api/metrics/query"] = fake
    d = call(server.get_version_split, "cart")
    by = {v["version"]: v for v in d["versions"]}
    assert by["v1"]["avg_ms"] == 2.0 and by["v2"]["avg_ms"] == 400.0


def test_get_version_split_avg_latency_missing_is_none(api):
    def fake(**params):
        if params["name"] == "istio_request_duration_milliseconds":
            return {"name": params["name"], "series": []}
        return {"name": "istio_requests_total", "series": [_vs("v1", "200", 0, 10)]}
    api["/api/metrics/query"] = fake
    d = call(server.get_version_split, "cart")
    assert d["versions"][0]["avg_ms"] is None


def test_get_version_split_no_data(api):
    api["/api/metrics/query"] = {"name": "istio_requests_total", "series": []}
    d = call(server.get_version_split, "ghost")
    assert d["versions"] == [] and "no istio_requests_total data" in d["note"]


def _flagged(flag, first, last):
    return {"attributes": {"response_flags": flag}, "datapoints": [{"timestamp": 1.0, "value": first}, {"timestamp": 2.0, "value": last}]}


def test_get_edge_decodes_response_flags(api):
    seen = {}

    def fake(**params):
        seen.update(params)
        return {"name": params["name"], "series": [_flagged("-", 0, 60), _flagged("UC", 0, 40)]}
    api["/api/service-map"] = {"nodes": [], "edges": [{"source": "a", "target": "b", "value": 100, "error_count": 0,
                                                       "p95": 1.0, "req_rate": 2.0, "mtls": True, "source_kind": "metrics"}]}
    api["/api/service-catalog"] = []
    api["/api/metrics/query"] = fake
    d = call(server.get_edge, "a", "b", minutes=5)
    assert seen["name"] == "istio_requests_total"
    assert seen["attribute.source_canonical_service"] == "a" and seen["attribute.destination_canonical_service"] == "b"
    rf = d["response_flags"]
    assert rf["total"] == 100 and rf["flags"][0]["flag"] == "UC" and rf["flags"][0]["share_pct"] == 40.0
    assert rf["flags"][0]["meaning"] and rf["flags"][0]["hint"]


def test_get_edge_without_metrics_has_empty_flags(api):
    api["/api/service-map"] = {"nodes": [], "edges": [{"source": "a", "target": "b", "value": 1}]}
    api["/api/service-catalog"] = []
    api["/api/metrics/query"] = lambda **p: {"name": p["name"], "series": []}
    assert call(server.get_edge, "a", "b")["response_flags"] == {"total": 0, "flags": []}


def test_what_changed_lists_events_and_changes_around_them(api):
    import time as _t
    now = _t.time()
    api["/api/events"] = [{"id": "e1", "timestamp": now - 120, "title": "applied flaky", "kind": "scenario",
                           "source": "demo", "attributes": {"scenario": "flaky"}}]

    def fake(**params):
        pts = lambda a, b, c: [{"timestamp": now - 180, "value": a}, {"timestamp": now - 120, "value": b}, {"timestamp": now - 30, "value": c}]  # noqa: E731
        return {"name": params["name"], "series": [
            {"attributes": {"destination_canonical_service": "pc", "response_flags": "-", "response_code": "200"}, "datapoints": pts(0, 100, 130)},
            {"attributes": {"destination_canonical_service": "pc", "response_flags": "UC", "response_code": "200"}, "datapoints": pts(0, 0, 90)}]}
    api["/api/metrics/query"] = fake
    d = call(server.what_changed, minutes=30)
    assert d["events"][0]["title"] == "applied flaky"
    ch = d["events"][0]["changes"]
    assert ch and ch[0]["service"] == "pc" and ch[0]["after"]["flags"] == {"UC": 90}


def test_what_changed_without_events_says_so(api):
    api["/api/events"] = []
    d = call(server.what_changed)
    assert d["events"] == [] and "no change markers" in d["note"].lower()


def test_suggest_authz_drafts_policy_from_observed_callers(api):
    def fake(**params):
        assert params["attribute.destination_canonical_service"] == "cartservice"
        return {"name": params["name"], "series": [
            {"attributes": {"source_canonical_service": "frontend", "source_principal": "spiffe://cluster.local/ns/boutique/sa/frontend",
                            "connection_security_policy": "mutual_tls", "destination_workload_namespace": "boutique"},
             "datapoints": [{"timestamp": 1.0, "value": 0}, {"timestamp": 2.0, "value": 9}]},
            {"attributes": {"source_canonical_service": "outsider", "source_principal": "", "connection_security_policy": "none",
                            "source_workload_namespace": "outside", "destination_workload_namespace": "boutique"},
             "datapoints": [{"timestamp": 1.0, "value": 0}, {"timestamp": 2.0, "value": 3}]}]}
    api["/api/metrics/query"] = fake
    d = call(server.suggest_authz, "cartservice")
    assert d["service"] == "cartservice" and [c["service"] for c in d["callers"]] == ["frontend"]
    assert d["plaintext_callers"][0]["service"] == "outsider"
    assert "kind: AuthorizationPolicy" in d["policy_yaml"] and "sa/frontend" in d["policy_yaml"]
    assert any("plaintext" in n.lower() for n in d["notes"]) and any("deni" in n.lower() for n in d["notes"])


def test_suggest_authz_without_traffic(api):
    api["/api/metrics/query"] = lambda **p: {"name": p["name"], "series": []}
    d = call(server.suggest_authz, "ghost")
    assert d["policy_yaml"] is None and d["callers"] == [] and "no" in d["notes"][0].lower()


def test_suggest_authz_warns_when_a_waypoint_is_the_caller(api):
    api["/api/metrics/query"] = lambda **p: {"name": p["name"], "series": [
        {"attributes": {"source_canonical_service": "waypoint", "source_principal": "spiffe://cluster.local/ns/boutique/sa/waypoint",
                        "connection_security_policy": "mutual_tls", "destination_workload_namespace": "boutique"},
         "datapoints": [{"timestamp": 1.0, "value": 1}, {"timestamp": 2.0, "value": 5}]}]}
    d = call(server.suggest_authz, "cartservice")
    assert any("waypoint" in n.lower() and "per-caller" in n.lower() for n in d["notes"])


def test_chart_map_diff_uses_the_latest_marker_and_names_the_changes(api):
    import time as _t
    now = _t.time()
    api["/api/service-map"] = {"nodes": [{"id": "a", "type": "service"}, {"id": "b", "type": "service"}],
                               "edges": [{"source": "a", "target": "b", "mtls": True}]}
    api["/api/events"] = [{"id": "e1", "timestamp": now - 100, "title": "applied flaky", "kind": "scenario", "source": "demo", "attributes": {}}]

    def pts(a, b, c):
        return [{"timestamp": now - 160, "value": a}, {"timestamp": now - 100, "value": b}, {"timestamp": now - 30, "value": c}]
    api["/api/metrics/query"] = lambda **p: {"name": p["name"], "series": [
        {"attributes": {"source_canonical_service": "a", "destination_canonical_service": "b", "response_flags": "-", "response_code": "200"}, "datapoints": pts(0, 100, 130)},
        {"attributes": {"source_canonical_service": "a", "destination_canonical_service": "b", "response_flags": "UC", "response_code": "200"}, "datapoints": pts(0, 0, 90)}]}
    out = server.chart_map_diff(minutes=30, window_seconds=120)
    assert out[0].data[:4] == b"\x89PNG"
    assert "applied flaky" in out[1] and "1 failures_up" in out[1].replace("failures rose", "failures_up")


def test_chart_map_diff_without_marker_compares_the_last_two_windows(api):
    api["/api/service-map"] = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}
    api["/api/events"] = []
    api["/api/metrics/query"] = lambda **p: {"name": p["name"], "series": []}
    out = server.chart_map_diff()
    assert out[0].data[:4] == b"\x89PNG" and "last" in out[1].lower()


def _jspan(i, service, start_ms, dur_ms, parent=None):
    s = {"spanId": f"{i:016x}", "serviceName": service, "name": f"op-{i}",
         "startTimeUnixNano": str(start_ms * 1_000_000), "endTimeUnixNano": str((start_ms + dur_ms) * 1_000_000)}
    if parent:
        s["parentSpanId"] = f"{parent:016x}"
    return s


def test_chart_trace_path_draws_the_journey_and_reports_mesh_share(api):
    api["/api/service-map"] = {"nodes": [{"id": "shop-ingress-istio"}, {"id": "frontend"}, {"id": "waypoint"}, {"id": "cart"}],
                               "edges": [{"source": "shop-ingress-istio", "target": "frontend"}, {"source": "frontend", "target": "waypoint"},
                                         {"source": "waypoint", "target": "cart"}]}
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": [_jspan(1, "shop-ingress-istio", 0, 100), _jspan(2, "frontend", 5, 90, 1),
                                                         _jspan(3, "waypoint.boutique", 10, 60, 2), _jspan(4, "cart", 15, 40, 3)]}
    out = server.chart_trace_path(T)
    assert out[0].data[:4] == b"\x89PNG"
    assert "3 hops" in out[1] and "30%" in out[1] and "waypoint" in out[1]


def test_chart_trace_path_unknown_trace_and_single_service(api):
    api["/api/service-map"] = {"nodes": [], "edges": []}
    assert "not found" in call(server.chart_trace_path, "ff" * 16)["error"].lower()
    api[f"/api/traces/{T}"] = {"trace_id": T, "spans": [_jspan(1, "a", 0, 5)]}
    assert "no service hops" in call(server.chart_trace_path, T)["error"].lower()


def test_get_version_split_flags_a_much_slower_version_and_a_version_with_more_errors(api):
    def hist(count, total):
        return {"count": count, "sum": total, "bucketCounts": [], "explicitBounds": []}

    def lat(version, c0, s0, c1, s1):
        return {"attributes": {"destination_version": version, "destination_canonical_service": "cart"},
                "datapoints": [{"timestamp": 1.0, "value": None, "histogram": hist(c0, s0)},
                               {"timestamp": 2.0, "value": None, "histogram": hist(c1, s1)}]}

    def fake(**params):
        if params["name"] == "istio_request_duration_milliseconds":
            return {"name": params["name"], "series": [lat("v1", 0, 0, 90, 90), lat("v2", 0, 0, 10, 4000)]}
        return {"name": "istio_requests_total", "series": [_vs("v1", "200", 0, 90), _vs("v2", "200", 0, 5), _vs("v2", "500", 0, 5)]}
    api["/api/metrics/query"] = fake
    d = call(server.get_version_split, "cart")
    assert any("v2" in f and "slower" in f and "400" in f for f in d["findings"])         # 400 ms vs 1 ms
    assert any("v2" in f and "error" in f.lower() for f in d["findings"])                 # 50% errors vs 0%


def test_get_version_split_has_no_findings_when_versions_look_alike(api):
    def hist(count, total):
        return {"count": count, "sum": total, "bucketCounts": [], "explicitBounds": []}

    def lat(version, c1, s1):
        return {"attributes": {"destination_version": version, "destination_canonical_service": "cart"},
                "datapoints": [{"timestamp": 1.0, "value": None, "histogram": hist(0, 0)},
                               {"timestamp": 2.0, "value": None, "histogram": hist(c1, s1)}]}

    def fake(**params):
        if params["name"] == "istio_request_duration_milliseconds":
            return {"name": params["name"], "series": [lat("v1", 90, 180), lat("v2", 10, 22)]}
        return {"name": "istio_requests_total", "series": [_vs("v1", "200", 0, 90), _vs("v2", "200", 0, 10)]}
    api["/api/metrics/query"] = fake
    assert call(server.get_version_split, "cart")["findings"] == []
