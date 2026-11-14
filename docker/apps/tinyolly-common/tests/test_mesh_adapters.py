"""F5: pure adapter turning Istio metric series into service-to-service edges."""
from tinyolly_common.mesh_adapters import metric_edges


def _s(src, dst, values, policy="mutual_tls", reporter="destination", code=None):
    attrs = {"source_canonical_service": src, "destination_canonical_service": dst,
             "connection_security_policy": policy, "reporter": reporter}
    if code:
        attrs["response_code"] = code
    return {"attributes": attrs, "datapoints": [{"timestamp": 100 + i, "value": v} for i, v in enumerate(values)]}


def _e(edges, s, t):
    return next(e for e in edges if e["source"] == s and e["target"] == t)


def test_count_is_counter_delta():
    e = _e(metric_edges([_s("a", "b", [10, 14, 25])]), "a", "b")
    assert e["count"] == 15 and e["mtls"] is True and e["errors"] == 0


def test_single_datapoint_uses_its_value():
    assert _e(metric_edges([_s("a", "b", [7])]), "a", "b")["count"] == 7


def test_both_reporters_are_not_double_counted():
    edges = metric_edges([_s("a", "b", [0, 10], reporter="source"), _s("a", "b", [0, 10], reporter="destination")])
    assert len(edges) == 1 and edges[0]["count"] == 10


def test_plaintext_series_makes_edge_not_mtls():
    edges = metric_edges([_s("a", "b", [0, 5]), _s("a", "b", [0, 3], policy="none")])
    assert _e(edges, "a", "b")["mtls"] is False


def test_5xx_series_count_as_errors():
    edges = metric_edges([_s("a", "b", [0, 20], code="200"), _s("a", "b", [0, 4], code="503")])
    e = _e(edges, "a", "b")
    assert e["errors"] == 4


def test_unknown_and_missing_names_are_skipped():
    edges = metric_edges([_s("unknown", "b", [0, 5]), _s("a", "", [0, 5]), _s("a", "c", [0, 5])])
    assert [(e["source"], e["target"]) for e in edges] == [("a", "c")]


def test_falls_back_to_workload_labels():
    s = {"attributes": {"source_workload": "x", "destination_workload": "y"}, "datapoints": [{"timestamp": 1, "value": 2}]}
    assert _e(metric_edges([s]), "x", "y")["count"] == 2


def test_empty_input():
    assert metric_edges([]) == []
