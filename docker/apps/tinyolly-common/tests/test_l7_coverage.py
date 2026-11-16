"""L7 coverage: which edges have request-level data (a waypoint or traces) versus connection counts only (ztunnel L4)."""
from tinyolly_common.mesh_adapters import merge_graph, metric_edges, posture


def series(src, dst, values, code=None):
    attrs = {"source_canonical_service": src, "destination_canonical_service": dst, "connection_security_policy": "mutual_tls"}
    if code:
        attrs["response_code"] = code
    return {"attributes": attrs, "datapoints": [{"timestamp": float(i), "value": float(v)} for i, v in enumerate(values)]}


def test_metric_edges_mark_request_level_series_as_l7():
    edges = {(e["source"], e["target"]): e for e in metric_edges([
        series("a", "b", [0, 5]),                      # tcp only
        series("a", "c", [0, 5]), series("a", "c", [0, 9], code="200"),     # tcp and request metrics
        series("a", "d", [0, 3], code="200")])}
    assert edges[("a", "b")]["l7"] is False
    assert edges[("a", "c")]["l7"] is True and edges[("a", "d")]["l7"] is True


def test_merge_graph_ors_l7_across_parallel_edges():
    g = merge_graph({"nodes": [{"id": "a"}, {"id": "a.ns"}, {"id": "b"}],
                     "edges": [{"source": "a", "target": "b", "value": 1, "l7": False},
                               {"source": "a.ns", "target": "b", "value": 2, "l7": True}]}, {"ns"})
    assert len(g["edges"]) == 1 and g["edges"][0]["l7"] is True


def test_posture_reports_l7_coverage_and_the_l4_only_edges():
    g = {"edges": [{"source": "a", "target": "b", "value": 10, "mtls": True, "l7": True},
                   {"source": "a", "target": "c", "value": 30, "mtls": True, "l7": False},
                   {"source": "b", "target": "c", "value": 5, "mtls": True},                  # no flag: counts as L4 only
                   {"source": "c", "target": "d", "value": 1, "mtls": True, "l7": True}]}
    p = posture(g)
    assert p["l7_edges"] == 2 and p["l7_pct"] == 50.0
    assert [(e["source"], e["target"]) for e in p["l4_only"]] == [("a", "c"), ("b", "c")]      # busiest first
    assert p["l4_only"][0]["value"] == 30


def test_posture_with_no_edges_has_zero_l7():
    p = posture({"edges": []})
    assert p["l7_edges"] == 0 and p["l7_pct"] == 0.0 and p["l4_only"] == []
