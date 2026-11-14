"""F2/F3: node roles and merging `.namespace` proxy/app identities in a service graph."""
from tinyolly_common.mesh_adapters import canonical_name, merge_graph, metric_namespaces, node_role

NS = {"boutique"}


def _g(nodes, edges):
    return {"nodes": [{"id": n, "label": n, "type": "service", "metrics": m} for n, m in nodes.items()],
            "edges": [dict({"source": s, "target": t, "value": 1, "p95": 0, "req_rate": 0, "error_count": 0,
                            "source_kind": "traces", "mtls": None}, **kw) for s, t, kw in edges]}


def test_canonical_name_strips_only_known_namespace():
    assert canonical_name("waypoint.boutique", NS) == "waypoint"
    assert canonical_name("api.v1", NS) == "api.v1"
    assert canonical_name("frontend", NS) == "frontend"
    assert canonical_name("waypoint.boutique", set()) == "waypoint.boutique"


def test_node_roles():
    assert node_role("waypoint") == "waypoint"
    assert node_role("shop-ingress-istio") == "gateway"
    assert node_role("ztunnel") == "ztunnel"
    assert node_role("frontend") == "service"


def test_metric_namespaces_collects_both_sides():
    s = [{"attributes": {"source_workload_namespace": "a", "destination_workload_namespace": "b"}, "datapoints": []},
         {"attributes": {}, "datapoints": []}]
    assert metric_namespaces(s) == {"a", "b"}


def test_merge_combines_nodes_keeping_larger_metrics():
    g = _g({"waypoint": {"span_count": 1}, "waypoint.boutique": {"span_count": 50}, "frontend": {}}, [])
    out = merge_graph(g, NS)
    ids = [n["id"] for n in out["nodes"]]
    assert sorted(ids) == ["frontend", "waypoint"]
    wp = next(n for n in out["nodes"] if n["id"] == "waypoint")
    assert wp["metrics"]["span_count"] == 50 and wp["role"] == "waypoint" and wp["label"] == "waypoint"


def test_merge_combines_parallel_edges():
    g = _g({"frontend": {}, "waypoint": {}, "waypoint.boutique": {}},
           [("frontend", "waypoint", {"value": 5, "source_kind": "metrics", "mtls": True, "p95": 0}),
            ("frontend", "waypoint.boutique", {"value": 100, "error_count": 7, "p95": 9.5, "req_rate": 2.0})])
    out = merge_graph(g, NS)
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert (e["source"], e["target"]) == ("frontend", "waypoint")
    assert e["value"] == 100 and e["error_count"] == 7 and e["p95"] == 9.5 and e["req_rate"] == 2.0
    assert e["source_kind"] == "traces+metrics" and e["mtls"] is True


def test_merge_drops_self_loops():
    g = _g({"waypoint": {}, "waypoint.boutique": {}}, [("waypoint", "waypoint.boutique", {})])
    assert merge_graph(g, NS)["edges"] == []


def test_empty_namespaces_is_layered_but_adds_roles():
    g = _g({"waypoint": {}, "waypoint.boutique": {}}, [("waypoint", "waypoint.boutique", {})])
    out = merge_graph(g, set())
    assert len(out["nodes"]) == 2 and len(out["edges"]) == 1
    assert all("role" in n for n in out["nodes"])
