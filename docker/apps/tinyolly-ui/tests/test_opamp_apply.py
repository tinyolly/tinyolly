"""POST /api/opamp/config pushes a config to every connected collector: it must validate first."""
import asyncio
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import opamp

GOOD = """receivers:
  otlp:
    protocols:
      grpc: {}
exporters:
  debug: {}
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
"""


class Recorder:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.fail_with = None


class FakeResponse:
    status = 200

    async def json(self):
        return {"status": "pending"}

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, rec):
        self.rec = rec

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, json=None, timeout=None):
        if self.rec.fail_with:
            raise self.rec.fail_with
        self.rec.posts.append((url, json))
        return FakeResponse()

    def get(self, url, params=None, timeout=None):
        if self.rec.fail_with:
            raise self.rec.fail_with
        self.rec.gets.append((url, params))
        return FakeResponse()


@pytest.fixture
def env(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(opamp.aiohttp, "ClientSession", lambda *a, **k: FakeSession(rec))

    def no_binary(_config):                      # the otelcol binary is not installed in the test environment
        raise FileNotFoundError

    monkeypatch.setattr(opamp, "_run_otelcol_validate", no_binary)
    app = FastAPI()
    app.include_router(opamp.router)
    return TestClient(app), rec, monkeypatch


@pytest.mark.parametrize("config", ["42", "- a\n- b\n", "just a string", "null", "", "   \n"])
def test_apply_rejects_configs_that_are_not_a_mapping(env, config):
    client, rec, _ = env
    r = client.post("/api/opamp/config", json={"config": config})
    assert r.status_code == 400, r.text
    assert rec.posts == [], "an invalid config must never be forwarded to the collectors"


def test_apply_rejects_structurally_invalid_collector_config(env):
    client, rec, _ = env
    r = client.post("/api/opamp/config", json={"config": "receivers: {}\n"})
    assert r.status_code == 400
    assert rec.posts == []


def test_apply_rejects_file_and_http_config_providers(env):
    client, rec, _ = env
    bad = GOOD.replace("grpc: {}", "grpc:\n        endpoint: ${file:/etc/hostname}")
    assert client.post("/api/opamp/config", json={"config": bad}).status_code == 400
    bad = GOOD.replace("debug: {}", "debug:\n    verbosity: ${HTTPS:example.com/x}")
    assert client.post("/api/opamp/config", json={"config": bad}).status_code == 400
    assert rec.posts == []


def test_apply_rejects_oversized_config_and_bad_instance_id(env):
    client, rec, _ = env
    assert client.post("/api/opamp/config", json={"config": "a: " + "x" * 1_000_001}).status_code == 422
    assert client.post("/api/opamp/config", json={"config": GOOD, "instance_id": "x&y=1"}).status_code == 422
    assert client.post("/api/opamp/config", json={"config": GOOD, "instance_id": "a" * 200}).status_code == 422
    assert rec.posts == []


def test_apply_forwards_a_valid_config(env):
    client, rec, _ = env
    r = client.post("/api/opamp/config", json={"config": GOOD, "instance_id": "01a1c2d6-3eca"})
    assert r.status_code == 200, r.text
    assert len(rec.posts) == 1
    url, payload = rec.posts[0]
    assert url.endswith("/config") and payload == {"config": GOOD, "instance_id": "01a1c2d6-3eca"}


def test_validation_timeout_fails_closed(env):
    client, rec, mp = env

    def slow(_config):
        raise subprocess.TimeoutExpired("otelcol-contrib", 10)

    mp.setattr(opamp, "_run_otelcol_validate", slow)
    r = client.post("/api/opamp/validate", json={"config": GOOD})
    assert r.status_code == 200 and r.json()["valid"] is False
    assert client.post("/api/opamp/config", json={"config": GOOD}).status_code == 400
    assert rec.posts == []


def test_validate_does_not_crash_on_non_mapping_yaml(env):
    client, _, _ = env
    for cfg in ["42", "- a", "service: 1\nreceivers: {}\nexporters: {}", "service:\n  pipelines: [a]\nreceivers: {}\nexporters: {}"]:
        r = client.post("/api/opamp/validate", json={"config": cfg})
        assert r.status_code == 200 and r.json()["valid"] is False, (cfg, r.text)


def test_get_config_passes_instance_id_as_a_param_not_in_the_url(env):
    client, rec, _ = env
    assert client.get("/api/opamp/config", params={"instance_id": "abc-1"}).status_code == 200
    url, params = rec.gets[0]
    assert "?" not in url and params == {"instance_id": "abc-1"}
    assert client.get("/api/opamp/config", params={"instance_id": "a&b=1"}).status_code == 422


@pytest.mark.parametrize("error", [asyncio.TimeoutError(), opamp.aiohttp.ClientConnectionError("Cannot connect to host opamp-server:4321")])
def test_opamp_server_timeouts_and_errors_are_503_without_leaking_details(env, error):
    client, rec, _ = env
    rec.fail_with = error
    for r in (client.get("/api/opamp/config"), client.post("/api/opamp/config", json={"config": GOOD})):
        assert r.status_code == 503, r.text
        assert "opamp-server" not in r.text and "4321" not in r.text
