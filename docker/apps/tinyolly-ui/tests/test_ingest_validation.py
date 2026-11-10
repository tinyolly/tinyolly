"""JSON ingest: full OTLP payloads go through the shared parsers; wrong shapes are 400, not 500."""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_alert_manager, get_storage
from app.routers import ingest
from tinyolly_common.storage_sqlite import StorageSQLite

TID = "0123456789abcdef0123456789abcdef"
SID = "0123456789abcdef"


class Alerts:
    async def check_span_error(self, *a, **k):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    class Counter:
        def add(self, *a, **k):
            pass

    monkeypatch.setattr(ingest, "get_ingestion_metrics", lambda: {"ingestion_counter": Counter(), "storage_operations_counter": Counter()})
    storage = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=60)
    app = FastAPI()
    app.include_router(ingest.router)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_alert_manager] = lambda: Alerts()
    return TestClient(app)


def _traces(trace_id, span_id):
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
            "scopeSpans": [{"spans": [{"traceId": trace_id, "spanId": span_id, "name": "op",
                                       "startTimeUnixNano": "1", "endTimeUnixNano": "2"}]}]}]}


@pytest.mark.parametrize("tid,sid", [(TID, SID),
                                     (base64.b64encode(bytes.fromhex(TID)).decode(), base64.b64encode(bytes.fromhex(SID)).decode())])
def test_otlp_json_traces_keep_service_and_hex_ids(client, tid, sid):
    assert client.post("/v1/traces", json=_traces(tid, sid)).status_code == 200
    import asyncio
    storage = client.app.dependency_overrides[get_storage]()
    got = asyncio.run(storage.get_trace_spans(TID))
    assert len(got) == 1 and got[0]["serviceName"] == "checkout" and got[0]["spanId"] == SID


@pytest.mark.parametrize("path,body", [
    ("/v1/traces", [1, 2]), ("/v1/traces", {"resourceSpans": "x"}), ("/v1/traces", {"spans": 5}),
    ("/v1/logs", {"resourceLogs": {}}), ("/v1/logs", "str"), ("/v1/metrics", {"resourceMetrics": 1}), ("/v1/metrics", 7),
])
def test_wrong_shapes_are_400(client, path, body):
    assert client.post(path, json=body).status_code == 400


def test_otlp_json_logs_resource_logs_are_parsed(client):
    import asyncio
    payload = {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]},
               "scopeLogs": [{"logRecords": [{"timeUnixNano": "1700000000000000000", "severityText": "ERROR",
                                              "body": {"stringValue": "boom"}, "traceId": TID, "spanId": SID}]}]}]}
    assert client.post("/v1/logs", json=payload).status_code == 200
    storage = client.app.dependency_overrides[get_storage]()
    logs = asyncio.run(storage.get_logs(limit=10))
    assert len(logs) == 1 and logs[0]["message"] == "boom" and logs[0]["service_name"] == "api" and logs[0]["trace_id"] == TID
