"""F1: kind-aware RED in get_service_catalog. Server-side spans define rate, errors and latency."""
import pytest

SERVER, CLIENT, INTERNAL, CONSUMER = 2, 3, 1, 5
ERR = {"code": 2}
T0 = 1_700_000_000 * 10**9
SEC = 10**9


def _span(n, service, kind, start_s, dur_s, error=False, trace=None):
    return service, {
        "traceId": trace or "%032x" % n, "spanId": "%016x" % n, "parentSpanId": "", "name": f"op{n}", "kind": kind,
        "startTimeUnixNano": str(T0 + int(start_s * SEC)), "endTimeUnixNano": str(T0 + int((start_s + dur_s) * SEC)),
        "status": ERR if error else {}}


async def _ingest(storage, items):
    by_service = {}
    for service, span in items:
        by_service.setdefault(service, []).append(span)
    rs = [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": s}}]},
           "scopeSpans": [{"spans": spans}]} for s, spans in by_service.items()]
    await storage.store_traces({"resourceSpans": rs})


def _svc(catalog, name):
    return next(c for c in catalog if c["name"] == name)


@pytest.mark.asyncio
async def test_client_spans_do_not_double_count_rate(storage):
    items = []
    for i in range(20):  # 20 SERVER spans of 0.5s back to back: window is exactly 10s
        items.append(_span(i + 1, "api", SERVER, i * 0.5, 0.5))
        items.append(_span(i + 101, "api", CLIENT, i * 0.5, 0.5))
    await _ingest(storage, items)
    api = _svc(await storage.get_service_catalog(), "api")
    assert api["rate"] == 2.0           # 20 server spans over a 10s window
    assert api["span_count"] == 40          # span_count still counts every span


@pytest.mark.asyncio
async def test_error_rate_uses_server_spans_only(storage):
    items = [_span(1, "api", SERVER, 0, 1, error=True)] + [_span(i, "api", SERVER, 0, 1) for i in (2, 3, 4)]
    items += [_span(i + 10, "api", CLIENT, 0, 1, error=True) for i in range(4)]
    await _ingest(storage, items)
    assert _svc(await storage.get_service_catalog(), "api")["error_rate"] == 25.0


@pytest.mark.asyncio
async def test_latency_percentiles_ignore_client_spans(storage):
    items = [_span(i, "api", SERVER, 0, 0.1) for i in range(1, 6)]
    items += [_span(i + 10, "api", CLIENT, 0, 5.0) for i in range(5)]
    await _ingest(storage, items)
    api = _svc(await storage.get_service_catalog(), "api")
    assert api["duration_p50"] == 100.0 and api["duration_p95"] == 100.0 and api["duration_p99"] == 100.0


@pytest.mark.asyncio
async def test_consumer_spans_count_like_server_spans(storage):
    items = [_span(i, "worker", CONSUMER, i, 1) for i in range(1, 5)]
    items += [_span(i + 10, "worker", INTERNAL, i, 1, error=True) for i in range(4)]
    await _ingest(storage, items)
    w = _svc(await storage.get_service_catalog(), "worker")
    assert w["rate"] == 1.0 and w["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_service_without_server_spans_falls_back_to_all_spans(storage):
    items = [_span(i, "batch", INTERNAL, i * 0.5, 0.5, error=(i == 1)) for i in range(1, 9)]
    items += [_span(20, "batch", CLIENT, 0, 4)]
    await _ingest(storage, items)
    b = _svc(await storage.get_service_catalog(), "batch")
    assert b["rate"] == 2.0              # 9 spans: all counted; window 0 .. 4.5s
    assert b["error_rate"] == round(100 / 9, 2)


@pytest.mark.asyncio
async def test_window_is_at_least_one_second(storage):
    items = [_span(i, "api", SERVER, 0.01 * i, 0.01) for i in range(1, 4)]
    await _ingest(storage, items)
    assert _svc(await storage.get_service_catalog(), "api")["rate"] == 3.0


@pytest.mark.asyncio
async def test_string_kind_names_are_understood(storage):
    items = [_span(i, "api", "SPAN_KIND_SERVER", i, 1) for i in range(1, 11)]
    items += [_span(i + 20, "api", "SPAN_KIND_CLIENT", i, 1, error=True) for i in range(10)]
    await _ingest(storage, items)
    api = _svc(await storage.get_service_catalog(), "api")
    assert api["rate"] == 1.0 and api["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_rate_is_float_and_zero_without_spans(storage):
    assert await storage.get_service_catalog() == []
    await _ingest(storage, [_span(1, "api", SERVER, 0, 2)])
    assert _svc(await storage.get_service_catalog(), "api")["rate"] == 0.5
