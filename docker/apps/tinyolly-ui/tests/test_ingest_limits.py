"""Ingest endpoints must enforce the body size cap even without a Content-Length header (chunked requests)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_alert_manager, get_storage
from app.routers import ingest

MAX = 5 * 1024 * 1024


class FakeStorage:
    def __init__(self):
        self.spans = []

    async def store_spans(self, spans):
        self.spans.extend(spans)

    async def store_logs(self, logs):
        pass

    async def store_metrics(self, metrics):
        pass


class FakeAlerts:
    async def check_span_error(self, *a, **k):
        pass

    async def check_log_error(self, *a, **k):
        pass

    async def check_metric_error(self, *a, **k):
        pass


@pytest.fixture
def client(monkeypatch):
    class Counter:
        def add(self, *a, **k):
            pass

    monkeypatch.setattr(ingest, "get_ingestion_metrics", lambda: {"ingestion_counter": Counter(), "storage_operations_counter": Counter()})
    storage = FakeStorage()
    app = FastAPI()
    app.include_router(ingest.router)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_alert_manager] = lambda: FakeAlerts()
    c = TestClient(app)
    c.storage = storage
    return c


def _big_body(n=MAX + 1024):
    return b'{"spans":[{"name":"x","pad":"' + b"a" * n + b'"}]}'


def _chunks(body, size=65536):
    for i in range(0, len(body), size):
        yield body[i:i + size]


@pytest.mark.parametrize("path", ["/v1/traces", "/v1/logs", "/v1/metrics"])
def test_oversized_content_length_is_rejected(client, path):
    r = client.post(path, content=_big_body(), headers={"content-type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("path", ["/v1/traces", "/v1/logs", "/v1/metrics"])
def test_oversized_chunked_body_is_rejected(client, path):
    # A generator body is sent with Transfer-Encoding: chunked and no Content-Length header.
    r = client.post(path, content=_chunks(_big_body()), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_normal_chunked_body_still_works(client):
    body = json.dumps({"spans": [{"name": "ok", "traceId": "t", "spanId": "s"}]}).encode()
    r = client.post("/v1/traces", content=_chunks(body, 8), headers={"content-type": "application/json"})
    assert r.status_code == 200
    assert client.storage.spans and client.storage.spans[0]["name"] == "ok"


@pytest.mark.parametrize("path", ["/v1/traces", "/v1/logs", "/v1/metrics"])
def test_non_numeric_content_length_is_a_400_not_a_500(client, path):
    r = client.post(path, content=b'{"spans":[]}', headers={"content-type": "application/json", "content-length": "abc"})
    assert r.status_code in (400, 422)


def test_invalid_json_is_still_a_400(client):
    r = client.post("/v1/traces", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
