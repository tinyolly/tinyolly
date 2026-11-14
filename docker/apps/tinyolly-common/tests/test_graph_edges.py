"""F4: service-graph edges report error_count and a req_rate computed from the real time window."""
import pytest

ERR = {"code": 2}
T0 = 1_700_000_000 * 10**9
SEC = 10**9


def _res(service, spans):
    return {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
            "scopeSpans": [{"spans": spans}]}


def _sp(n, parent, start_s, dur_s, error=False, attrs=None, trace=None):
    return {"traceId": trace or "%032x" % n, "spanId": "%016x" % n, "parentSpanId": parent, "name": f"op{n}",
            "startTimeUnixNano": str(T0 + int(start_s * SEC)), "endTimeUnixNano": str(T0 + int((start_s + dur_s) * SEC)),
            "status": ERR if error else {}, "attributes": attrs or []}


async def _calls(storage, n, step, dur, errors=(), callee="b", caller="a"):
    """n traces; in each, `caller` calls `callee`. Call i starts at i*step seconds and lasts `dur` seconds."""
    for i in range(n):
        parent = _sp(i + 1, "", i * step, dur)
        child = _sp(i + 1001, "%016x" % (i + 1), i * step, dur, error=i in errors, trace=parent["traceId"])
        await storage.store_traces({"resourceSpans": [_res(caller, [parent]), _res(callee, [child])]})


def _edge(graph, s, t):
    return next(e for e in graph["edges"] if e["source"] == s and e["target"] == t)


@pytest.mark.asyncio
async def test_edge_error_count_counts_failed_callee_spans(storage):
    await _calls(storage, 10, 1, 1, errors={2, 5})
    e = _edge(await storage.get_service_graph(), "a", "b")
    assert e["error_count"] == 2
    assert e["value"] == 10


@pytest.mark.asyncio
async def test_edge_error_count_is_zero_when_healthy(storage):
    await _calls(storage, 4, 1, 1)
    assert _edge(await storage.get_service_graph(), "a", "b")["error_count"] == 0


@pytest.mark.asyncio
async def test_req_rate_uses_the_real_window(storage):
    await _calls(storage, 20, 0.5, 0.5)       # 20 calls, back to back, window exactly 10s
    assert _edge(await storage.get_service_graph(), "a", "b")["req_rate"] == 2.0


@pytest.mark.asyncio
async def test_req_rate_window_is_at_least_one_second(storage):
    await _calls(storage, 3, 0.01, 0.01)
    assert _edge(await storage.get_service_graph(), "a", "b")["req_rate"] == 3.0


@pytest.mark.asyncio
async def test_database_edge_gets_the_same_fields(storage):
    for i in range(4):
        db = _sp(i + 1, "", i, 1, error=(i == 0), attrs=[{"key": "db.system", "value": {"stringValue": "redis"}}])
        await storage.store_traces({"resourceSpans": [_res("cart", [db])]})
    e = _edge(await storage.get_service_graph(), "cart", "redis")
    assert e["error_count"] == 1 and e["req_rate"] == 1.0 and e["value"] == 4


@pytest.mark.asyncio
async def test_existing_edge_fields_are_unchanged(storage):
    await _calls(storage, 5, 1, 1)
    e = _edge(await storage.get_service_graph(), "a", "b")
    assert set(e) >= {"source", "target", "value", "p95", "req_rate", "error_count"}
    assert e["p95"] == 1000.0
