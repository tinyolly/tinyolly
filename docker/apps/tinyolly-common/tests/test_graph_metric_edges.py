"""F5: the service graph includes edges derived from mesh metrics, even with no traces."""
import time

import pytest

NAME = "istio_tcp_connections_opened_total"


async def _put(storage, src, dst, vals, policy="mutual_tls"):
    now = time.time()
    for i, v in enumerate(vals):
        await storage.store_metrics([{
            "name": NAME, "type": "sum", "value": v, "timestamp": now - 10 + i,
            "attributes": {"source_canonical_service": src, "destination_canonical_service": dst,
                           "connection_security_policy": policy, "reporter": "destination"}}])


def _edge(g, s, t):
    return next(e for e in g["edges"] if e["source"] == s and e["target"] == t)


@pytest.mark.asyncio
async def test_metrics_only_map_has_nodes_and_edges(storage):
    await _put(storage, "frontend", "cart", [0, 12])
    g = await storage.get_service_graph()
    ids = {n["id"] for n in g["nodes"]}
    assert {"frontend", "cart"} <= ids
    e = _edge(g, "frontend", "cart")
    assert e["source_kind"] == "metrics" and e["value"] == 12 and e["mtls"] is True


@pytest.mark.asyncio
async def test_plaintext_edge_reports_mtls_false(storage):
    await _put(storage, "a", "b", [0, 3], policy="none")
    assert _edge(await storage.get_service_graph(), "a", "b")["mtls"] is False


@pytest.mark.asyncio
async def test_trace_edge_keeps_trace_numbers_and_gains_mtls(storage):
    from test_graph_edges import _calls
    await _calls(storage, 5, 1, 1)                     # a -> b from traces
    await _put(storage, "a", "b", [0, 99])
    e = _edge(await storage.get_service_graph(), "a", "b")
    assert e["value"] == 5 and e["source_kind"] == "traces+metrics" and e["mtls"] is True


@pytest.mark.asyncio
async def test_trace_only_edge_is_tagged_traces(storage):
    from test_graph_edges import _calls
    await _calls(storage, 3, 1, 1)
    e = _edge(await storage.get_service_graph(), "a", "b")
    assert e["source_kind"] == "traces" and e["mtls"] is None


@pytest.mark.asyncio
async def test_graph_merges_namespaced_names_by_default_and_layers_on_request(storage):
    now = time.time()
    for i, v in enumerate([0, 9]):
        await storage.store_metrics([{
            "name": NAME, "type": "sum", "value": v, "timestamp": now - 10 + i,
            "attributes": {"source_canonical_service": "frontend", "destination_canonical_service": "waypoint",
                           "source_workload_namespace": "shop", "destination_workload_namespace": "shop",
                           "connection_security_policy": "mutual_tls"}}])
    await storage.store_metrics([{"name": NAME, "type": "sum", "value": 1, "timestamp": now,
                                  "attributes": {"source_canonical_service": "waypoint.shop",
                                                 "destination_canonical_service": "cart",
                                                 "source_workload_namespace": "shop"}}])
    merged = await storage.get_service_graph()
    assert {n["id"] for n in merged["nodes"]} == {"frontend", "waypoint", "cart"}
    assert next(n for n in merged["nodes"] if n["id"] == "waypoint")["role"] == "waypoint"
    layered = await storage.get_service_graph(merge=False)
    assert {"waypoint", "waypoint.shop"} <= {n["id"] for n in layered["nodes"]}
