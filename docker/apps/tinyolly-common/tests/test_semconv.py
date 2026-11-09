"""Both legacy and current HTTP semantic-convention attribute names must render."""
import base64
import time

import pytest


def _otlp(trace_id, attrs):
    now = time.time_ns()
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]},
        "scopeSpans": [{"spans": [{
            "traceId": base64.b64encode(bytes.fromhex(trace_id)).decode(),
            "spanId": base64.b64encode(bytes.fromhex("eee19b7ec3c1b174")).decode(), "name": "GET /x", "kind": 2,
            "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 5_000_000),
            "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
        }]}],
    }]}


@pytest.mark.asyncio
@pytest.mark.parametrize("attrs,method,status", [
    ({"http.method": "GET", "http.status_code": "200"}, "GET", "200"),
    ({"http.request.method": "POST", "http.response.status_code": "201"}, "POST", "201"),
])
async def test_root_span_method_and_status(storage, attrs, method, status):
    tid = "5b8efff798038103d269b633813fc60c"
    await storage.store_traces(_otlp(tid, attrs))
    summary = await storage.get_trace_summary(tid)
    assert summary is not None
    assert summary["root_span_method"] == method
    assert str(summary["root_span_status_code"]) == status


@pytest.mark.asyncio
async def test_roundtrip_logs(storage):
    now = time.time_ns()
    await storage.store_logs_otlp({"resourceLogs": [{
        "resource": {"attributes": []},
        "scopeLogs": [{"logRecords": [{"timeUnixNano": str(now), "severityText": "INFO",
                                       "body": {"stringValue": "hello"}}]}],
    }]})
    logs = await storage.get_logs(limit=10)
    assert any("hello" in str(l) for l in logs)
