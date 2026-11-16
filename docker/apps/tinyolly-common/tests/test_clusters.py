"""Multicluster: Istio metrics carry source_cluster / destination_cluster; surface them on nodes, edges and posture."""
from tinyolly_common.mesh_adapters import (
    annotate_clusters,
    merge_graph,
    metric_edges,
    metric_only_edge,
    posture,
    trace_edge,
)


def series(src, dst, src_cluster=None, dst_cluster=None, values=(0, 5)):
    attrs = {"source_canonical_service": src, "destination_canonical_service": dst, "connection_security_policy": "mutual_tls"}
    if src_cluster is not None:
        attrs["source_cluster"] = src_cluster
    if dst_cluster is not None:
        attrs["destination_cluster"] = dst_cluster
    return {"attributes": attrs, "datapoints": [{"timestamp": float(i), "value": float(v)} for i, v in enumerate(values)]}


def test_metric_edges_carry_clusters_and_flag_cross_cluster():
    edges = {(e["source"], e["target"]): e for e in metric_edges([
        series("a", "b", "east", "east"), series("a", "c", "east", "west"), series("a", "d"),
        series("a", "e", "unknown", "west")])}
    assert edges[("a", "b")]["source_cluster"] == "east" and edges[("a", "b")]["cross_cluster"] is False
    assert edges[("a", "c")]["target_cluster"] == "west" and edges[("a", "c")]["cross_cluster"] is True
    assert "source_cluster" not in edges[("a", "d")] and edges[("a", "d")]["cross_cluster"] is False
    assert "source_cluster" not in edges[("a", "e")] and edges[("a", "e")]["cross_cluster"] is False     # "unknown" is not a cluster


def test_metric_only_edge_and_trace_edge_pass_clusters_through():
    e = metric_only_edge("a", "c", {"count": 1, "errors": 0, "mtls": True, "source_cluster": "east", "target_cluster": "west", "cross_cluster": True})
    assert e["source_cluster"] == "east" and e["target_cluster"] == "west" and e["cross_cluster"] is True
    t = trace_edge("a", "c", {"count": 1, "durations": [1.0], "spans": [(0, 1_000_000, False)]},
                   {"count": 1, "errors": 0, "mtls": True, "source_cluster": "east", "target_cluster": "west", "cross_cluster": True})
    assert t["cross_cluster"] is True and t["target_cluster"] == "west"
    assert "cross_cluster" not in trace_edge("a", "c", {"count": 1, "durations": [1.0], "spans": [(0, 1_000_000, False)]}, None)


def test_annotate_clusters_sets_node_cluster_and_keeps_the_graph():
    g = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "z"}],
         "edges": [{"source": "a", "target": "b", "source_cluster": "east", "target_cluster": "east"},
                   {"source": "a", "target": "c", "source_cluster": "east", "target_cluster": "west"}]}
    out = annotate_clusters(g)
    by = {n["id"]: n for n in out["nodes"]}
    assert by["a"]["cluster"] == "east" and by["b"]["cluster"] == "east" and by["c"]["cluster"] == "west"
    assert "cluster" not in by["z"] and len(out["edges"]) == 2


def test_merge_graph_keeps_cluster_fields():
    g = merge_graph({"nodes": [{"id": "a"}, {"id": "b"}],
                     "edges": [{"source": "a", "target": "b", "value": 1, "source_cluster": "east", "target_cluster": "west", "cross_cluster": True}]}, set())
    assert g["edges"][0]["cross_cluster"] is True


def test_posture_lists_clusters_and_cross_cluster_edges():
    g = {"edges": [{"source": "a", "target": "b", "mtls": True, "value": 3, "source_cluster": "east", "target_cluster": "east", "cross_cluster": False},
                   {"source": "a", "target": "c", "mtls": True, "value": 9, "source_cluster": "east", "target_cluster": "west", "cross_cluster": True},
                   {"source": "b", "target": "d", "mtls": True, "value": 1}]}
    p = posture(g)
    assert p["clusters"] == ["east", "west"] and p["cross_cluster_edges"] == 1
    assert p["cross_cluster"] == [{"source": "a", "target": "c", "source_cluster": "east", "target_cluster": "west", "value": 9}]
    q = posture({"edges": [{"source": "a", "target": "b", "mtls": True}]})
    assert q["clusters"] == [] and q["cross_cluster_edges"] == 0 and q["cross_cluster"] == []
