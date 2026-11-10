import base64
import time

import pytest

from tinyolly_common.otlp_utils import get_attr_value, normalize_id

TID = "0123456789abcdef0123456789abcdef"
SID = "0123456789abcdef"


def b64(h):
    return base64.b64encode(bytes.fromhex(h)).decode()


def test_normalize_id_accepts_hex_and_base64():
    assert normalize_id(TID, 16) == TID
    assert normalize_id(TID.upper(), 16) == TID
    assert normalize_id(b64(TID), 16) == TID
    assert normalize_id(SID, 8) == SID
    assert normalize_id(b64(SID), 8) == SID
    assert normalize_id(bytes.fromhex(SID), 8) == SID


@pytest.mark.parametrize("bad", [None, "", "zz", "not base64!!", "00" * 16, 123, b64(SID)])
def test_normalize_id_rejects_malformed(bad):
    assert normalize_id(bad, 16) == ""        # wrong length / zero / junk -> absent, never raises


def test_get_attr_value_prefers_key_order():
    span = {"attributes": [
        {"key": "http.request.method", "value": {"stringValue": "NEW"}},
        {"key": "http.method", "value": {"stringValue": "OLD"}},
    ]}
    assert get_attr_value(span, ["http.method", "http.request.method"]) == "OLD"
    assert get_attr_value(span, ["http.request.method", "http.method"]) == "NEW"
    assert get_attr_value(span, ["missing"]) is None


def _otlp(trace_id, span_id, parent=""):
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]},
            "scopeSpans": [{"spans": [{"traceId": trace_id, "spanId": span_id, "parentSpanId": parent, "name": "n",
                                       "startTimeUnixNano": "1", "endTimeUnixNano": "2"}]}]}]}


@pytest.mark.asyncio
async def test_hex_ids_and_bad_span_do_not_break_batch(storage):
    data = _otlp(TID, SID)
    data["resourceSpans"][0]["scopeSpans"][0]["spans"].append({"traceId": "garbage", "spanId": "x", "name": "bad"})
    spans = storage.parse_otlp_traces(data)
    assert [(s["traceId"], s["spanId"]) for s in spans] == [(TID, SID)]
    await storage.store_traces(data)
    assert (await storage.get_trace_summary(TID))["span_count"] == 1


@pytest.mark.asyncio
async def test_trace_summaries_batch_matches_single(storage):
    for i in range(3):
        await storage.store_traces(_otlp(("%032x" % (i + 1)), ("%016x" % (i + 1))))
    ids = await storage.get_recent_traces(10)
    batch = await storage.get_trace_summaries(ids)
    assert {b["trace_id"] for b in batch} == set(ids)
    assert batch[0] == await storage.get_trace_summary(batch[0]["trace_id"])


@pytest.mark.asyncio
async def test_span_details_batch_keeps_order_and_skips_missing(storage):
    await storage.store_traces(_otlp(TID, SID))
    out = await storage.get_spans_details_batch(["nope", SID])
    assert [o["span_id"] for o in out] == [SID]


@pytest.mark.asyncio
async def test_traces_table_no_longer_written(storage):
    await storage.store_traces(_otlp(TID, SID))
    conn = await storage._connect()
    try:
        async with conn.execute("SELECT COUNT(*) FROM traces") as cur:
            assert (await cur.fetchone())[0] == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_metric_cardinality_is_enforced_and_counted(storage):
    storage.max_cardinality = 3
    now = time.time()
    batch = [{"name": f"m{i}", "type": "gauge", "value": i, "timestamp": now} for i in range(6)]
    batch.append({"name": "m0", "type": "gauge", "value": 99, "timestamp": now})   # existing name still accepted
    await storage.store_metrics(batch)
    names = set(await storage.get_metric_names())
    assert names == {"m0", "m1", "m2"}
    stats = await storage.get_cardinality_stats()
    assert stats["dropped_count"] == 3 and set(stats["dropped_names"]) == {"m3", "m4", "m5"}
    assert (await storage.get_stats())["metrics_dropped"] == 3


@pytest.mark.asyncio
async def test_metrics_written_in_one_transaction(storage):
    now = time.time()
    await storage.store_metrics([{"name": "a", "type": "gauge", "value": 1, "timestamp": now},
                                 {"name": "b", "type": "sum", "value": 2, "timestamp": now}])
    assert set(await storage.get_metric_names()) == {"a", "b"}


@pytest.mark.asyncio
async def test_orphan_index_rows_removed(storage):
    await storage.store_traces(_otlp(TID, SID))
    conn = await storage._connect()
    try:
        await conn.execute("DELETE FROM spans")
        await conn.commit()
    finally:
        await conn.close()
    await storage._cleanup_expired_and_trim()
    assert await storage.get_recent_traces(10) == [] and await storage.get_recent_spans(10) == []


@pytest.mark.asyncio
async def test_close_stops_cleanup_task(storage):
    await storage.store_traces(_otlp(TID, SID))
    task = storage._cleanup_task
    assert task is not None
    await storage.close()
    assert task.done() and storage._cleanup_task is None
