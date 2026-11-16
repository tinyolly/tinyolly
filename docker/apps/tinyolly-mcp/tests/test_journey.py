"""journey.py: turn one trace into ordered service hops and a mesh-versus-app time split."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journey  # noqa: E402

MS = 1_000_000


def sp(i, service, start_ms, dur_ms, parent=None):
    s = {"spanId": f"{i:016x}", "serviceName": service, "name": f"op-{i}",
         "startTimeUnixNano": str(start_ms * MS), "endTimeUnixNano": str((start_ms + dur_ms) * MS)}
    if parent:
        s["parentSpanId"] = f"{parent:016x}"
    return s


CHAIN = [sp(1, "shop-ingress-istio", 0, 100),              # gateway (proxy), root
         sp(2, "frontend", 5, 90, parent=1),
         sp(3, "waypoint.boutique", 10, 60, parent=2),     # waypoint (proxy)
         sp(4, "productcatalogservice", 15, 40, parent=3)]


def test_hops_follow_service_boundaries_in_start_order():
    h = journey.journey_hops(CHAIN)
    assert [(x["order"], x["source"], x["target"]) for x in h] == [
        (1, "shop-ingress-istio", "frontend"), (2, "frontend", "waypoint.boutique"), (3, "waypoint.boutique", "productcatalogservice")]
    assert [x["duration_ms"] for x in h] == [90.0, 60.0, 40.0]
    assert [x["via_proxy"] for x in h] == [True, True, True]


def test_same_service_parent_child_are_not_hops_and_siblings_are_ordered_by_start():
    spans = [sp(1, "a", 0, 100), sp(2, "a", 1, 90, parent=1), sp(3, "c", 50, 10, parent=2), sp(4, "b", 20, 10, parent=2)]
    h = journey.journey_hops(spans)
    assert [(x["source"], x["target"]) for x in h] == [("a", "b"), ("a", "c")]
    assert [x["via_proxy"] for x in h] == [False, False]


def test_split_separates_proxy_self_time_from_app_time():
    s = journey.mesh_vs_app(CHAIN)
    # self time: ingress 100-90=10, waypoint 60-40=20 -> 30 ms in proxies of a 100 ms trace
    assert s["total_ms"] == 100.0 and s["proxy_ms"] == 30.0 and s["app_ms"] == 70.0 and s["hops"] == 3
    assert s["proxy_pct"] == 30.0


def test_empty_and_single_span_traces():
    assert journey.journey_hops([]) == [] and journey.journey_hops([sp(1, "a", 0, 5)]) == []
    assert journey.mesh_vs_app([]) == {"total_ms": 0.0, "proxy_ms": 0.0, "app_ms": 0.0, "proxy_pct": 0.0, "hops": 0}
    s = journey.mesh_vs_app([sp(1, "a", 0, 5)])
    assert s["total_ms"] == 5.0 and s["proxy_ms"] == 0.0 and s["hops"] == 0


def test_is_proxy_names():
    assert all(journey.is_proxy(n) for n in ("waypoint", "waypoint.boutique", "shop-ingress-istio", "istio-ingressgateway", "ztunnel"))
    assert not any(journey.is_proxy(n) for n in ("frontend", "cartservice", "gatewayservice-app-name-without"))
