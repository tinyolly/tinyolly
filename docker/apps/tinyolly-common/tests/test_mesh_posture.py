"""F7: mTLS and policy posture computed from the service graph; 403s counted as denied."""
import time

import pytest

from tinyolly_common.mesh_adapters import metric_edges, posture


def _s(src, dst, values, code=None, policy="mutual_tls"):
    attrs = {"source_canonical_service": src, "destination_canonical_service": dst,
             "connection_security_policy": policy}
    if code:
        attrs["response_code"] = code
    return {"attributes": attrs, "datapoints": [{"timestamp": i, "value": v} for i, v in enumerate(values)]}


def test_403_series_counted_as_denied():
    e = metric_edges([_s("a", "b", [0, 30], code="200"), _s("a", "b", [0, 6], code="403")])[0]
    assert e["denied"] == 6 and e["errors"] == 0


def _g(*edges):
    return {"nodes": [], "edges": [dict({"value": 1, "error_count": 0, "denied_count": 0, "mtls": None}, source=s, target=t, **kw)
                                    for s, t, kw in edges]}


def test_posture_counts_and_lists():
    g = _g(("a", "b", {"mtls": True}), ("b", "c", {"mtls": True}), ("a", "x", {"mtls": False, "value": 4}),
           ("c", "d", {}), ("a", "d", {"mtls": True, "denied_count": 9}))
    p = posture(g)
    assert p["total_edges"] == 5 and p["mtls_edges"] == 3 and p["plaintext_edges"] == 1 and p["unknown_edges"] == 1
    assert p["mtls_pct"] == 75.0
    assert p["plaintext"] == [{"source": "a", "target": "x", "value": 4}]
    assert p["denied"] == [{"source": "a", "target": "d", "count": 9}]


def test_posture_of_empty_graph():
    p = posture({"nodes": [], "edges": []})
    assert p["total_edges"] == 0 and p["mtls_pct"] == 0.0 and p["plaintext"] == [] and p["denied"] == []


@pytest.mark.asyncio
async def test_storage_posture_from_metrics(storage):
    now = time.time()
    for name, pol, code, vals in [("istio_requests_total", "mutual_tls", "200", [0, 10]),
                                  ("istio_requests_total", "mutual_tls", "403", [0, 3]),
                                  ("istio_tcp_connections_opened_total", "none", None, [0, 2])]:
        dst = "b" if pol == "mutual_tls" else "c"
        for i, v in enumerate(vals):
            attrs = {"source_canonical_service": "a", "destination_canonical_service": dst,
                     "connection_security_policy": pol}
            if code:
                attrs["response_code"] = code
            await storage.store_metrics([{"name": name, "type": "sum", "value": v, "timestamp": now - 5 + i, "attributes": attrs}])
    p = await storage.get_mesh_posture()
    assert p["mtls_edges"] == 1 and p["plaintext_edges"] == 1
    assert p["denied"] == [{"source": "a", "target": "b", "count": 3}]


def test_grpc_status_7_is_denied_and_other_nonzero_is_error():
    def s(g, v):
        a = _s("a", "b", v, code="200")
        a["attributes"]["grpc_response_status"] = g
        return a
    e = metric_edges([s("0", [0, 50]), s("7", [0, 5]), s("14", [0, 2])])[0]
    assert e["denied"] == 5 and e["errors"] == 2


def test_waypoint_local_reply_is_denied_against_the_addressed_service():
    s = {"attributes": {"source_canonical_service": "intruder", "destination_canonical_service": "unknown",
                        "destination_service_name": "cart", "reporter": "waypoint", "response_code": "200",
                        "response_flags": "-"},
         "datapoints": [{"timestamp": 0, "value": 0}, {"timestamp": 1, "value": 8}]}
    e = metric_edges([s])[0]
    assert (e["source"], e["target"], e["denied"]) == ("intruder", "cart", 8)


def test_upstream_failure_with_flag_is_an_error_not_a_denial():
    s = {"attributes": {"source_canonical_service": "a", "destination_canonical_service": "unknown",
                        "destination_service_name": "cart", "reporter": "waypoint", "response_code": "200",
                        "response_flags": "UH", "grpc_response_status": "14"},
         "datapoints": [{"timestamp": 0, "value": 0}, {"timestamp": 1, "value": 3}]}
    e = metric_edges([s])[0]
    assert e["denied"] == 0 and e["errors"] == 3


def test_deny_flagged_failed_connections_count_as_denied():
    """ztunnel flags L4 connections refused by policy (STRICT mTLS) with response_flags=DENY."""
    from tinyolly_common.mesh_adapters import metric_edges
    s = {"attributes": {"source_canonical_service": "outsider", "destination_canonical_service": "frontend",
                        "connection_security_policy": "unknown", "reporter": "destination", "response_flags": "DENY"},
         "datapoints": [{"timestamp": 1, "value": 0}, {"timestamp": 2, "value": 12}]}
    (e,) = metric_edges([s])
    assert e["denied"] == 12 and e["errors"] == 0 and e["mtls"] is False
