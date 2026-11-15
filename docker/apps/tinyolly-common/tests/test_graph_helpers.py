"""Pure helpers that build service-graph nodes and edges (used by StorageSQLite.get_service_graph)."""
from tinyolly_common.mesh_adapters import graph_node_list, metric_only_edge, trace_edge


def test_graph_node_list_defaults_type_and_metrics():
    out = graph_node_list({"a": {"type": "database", "metrics": {"span_count": 3}}, "b": {}})
    assert out == [
        {"id": "a", "label": "a", "type": "database", "metrics": {"span_count": 3}},
        {"id": "b", "label": "b", "type": "service", "metrics": {}},
    ]


def test_metric_only_edge_shape_and_denied_default():
    e = metric_only_edge("x", "y", {"count": 7, "errors": 2, "mtls": True})
    assert e == {"source": "x", "target": "y", "value": 7, "p95": 0, "req_rate": 0, "error_count": 2,
                 "denied_count": 0, "source_kind": "metrics", "mtls": True}
    assert metric_only_edge("x", "y", {"count": 1, "errors": 0, "mtls": False, "denied": 5})["denied_count"] == 5


def test_trace_edge_p95_errors_rate_without_metrics():
    # 20 calls, durations 1..20 ms; p95 index = int(20 * 0.95) = 19 -> 20 ms
    spans = [(i * 100_000_000, i * 100_000_000 + 1_000_000, i == 3) for i in range(20)]
    data = {"count": 20, "durations": [float(d) for d in range(20, 0, -1)], "spans": spans}
    e = trace_edge("a", "b", data, None)
    assert e["value"] == 20 and e["p95"] == 20.0 and e["error_count"] == 1
    # window = (last end - first start) = 1.9s + 1ms -> 20 / 1.901 = 10.52
    assert e["req_rate"] == 10.52
    assert (e["source_kind"], e["mtls"], e["denied_count"]) == ("traces", None, 0)


def test_trace_edge_with_metric_edge_and_short_window():
    data = {"count": 4, "durations": [2.0, 2.0, 2.0, 2.0], "spans": [(0, 2_000_000, False)] * 4}
    e = trace_edge("a", "b", data, {"count": 9, "errors": 0, "mtls": True, "denied": 3})
    assert e["req_rate"] == 4.0          # window floors at 1 second
    assert (e["source_kind"], e["mtls"], e["denied_count"]) == ("traces+metrics", True, 3)


def test_trace_edge_empty_data():
    e = trace_edge("a", "b", {"count": 0, "durations": [], "spans": []}, None)
    assert e["p95"] == 0 and e["req_rate"] == 0 and e["error_count"] == 0
