"""Origin guard, low-cardinality metric labels, websocket origin, alert webhook safety."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import setup_middleware
from app.core.origin import cors_origin_regex, origin_allowed
from app.managers import alerts as alerts_mod
from app.managers.alerts import AlertManager, validate_webhook_url
from app.managers.websocket import ConnectionManager
from models import AlertRule

LOCAL = ["http://localhost:*", "http://127.0.0.1:*"]


# ---- origin ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("origin,host,ok", [
    (None, "localhost:5005", True),                          # curl / collector: no Origin
    ("http://localhost:5005", "localhost:5005", True),
    ("http://localhost:3000", "localhost:5005", True),       # other local dev server
    ("http://127.0.0.1:8080", "localhost:5005", True),
    ("http://192.168.1.5:5005", "192.168.1.5:5005", True),   # same-origin over the LAN
    ("https://evil.example", "localhost:5005", False),
    ("http://localhost.evil.example", "localhost:5005", False),
    ("null", "localhost:5005", False),
    ("file://x", "localhost:5005", False),
])
def test_origin_allowed(origin, host, ok):
    assert origin_allowed(origin, host, LOCAL) is ok


def test_custom_pattern_and_regex():
    assert origin_allowed("https://app.example.com", "localhost:5005", ["https://*.example.com"])
    assert not origin_allowed("https://example.com.evil.io", "localhost:5005", ["https://*.example.com"])
    import re
    rx = cors_origin_regex(LOCAL)
    assert re.match(rx, "http://localhost:3000") and not re.match(rx, "http://evil.io")


class _M:
    def add(self, *a, **k):
        self.last = (a, k)


@pytest.fixture
def app_client(monkeypatch):
    from app.core import middleware
    rec = {k: _M() for k in ("request_counter", "response_time_histogram", "error_counter")}
    monkeypatch.setattr(middleware, "get_metrics", lambda: {**rec, "response_time_histogram": type("H", (), {"record": lambda *a, **k: None})()})
    app = FastAPI()
    setup_middleware(app)
    calls = []

    @app.post("/api/reset")
    async def reset():
        calls.append(1)
        return {"ok": True}

    @app.post("/admin/alerts")
    async def alerts():
        calls.append(2)
        return {"ok": True}

    @app.post("/v1/traces")
    async def ingest():
        return {"ok": True}

    @app.get("/api/traces/{trace_id}")
    async def trace(trace_id: str):
        return {"id": trace_id}

    return TestClient(app), calls, rec


def test_cross_site_post_to_api_is_blocked_but_curl_is_not(app_client):
    c, calls, _ = app_client
    assert c.post("/api/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    assert calls == []
    assert c.post("/api/reset").status_code == 200
    assert c.post("/api/reset", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert len(calls) == 2


def test_admin_writes_are_guarded_and_ingest_is_exempt(app_client):
    c, calls, _ = app_client
    assert c.post("/admin/alerts", headers={"Origin": "https://evil.example"}).status_code == 403
    assert 2 not in calls
    assert c.post("/v1/traces", headers={"Origin": "https://browser-app.example"}).status_code == 200   # browser OTLP exporters


def test_metric_endpoint_label_is_the_route_template(app_client):
    c, _, rec = app_client
    c.get("/api/traces/abc123")
    assert rec["request_counter"].last[0][1]["endpoint"] == "/api/traces/{trace_id}"
    c.get("/wp-admin/setup.php?x=1")
    assert rec["request_counter"].last[0][1]["endpoint"] == "unmatched"


# ---- websocket manager ----------------------------------------------------------------------------------
class _WS:
    def __init__(self, mgr=None, drop=None):
        self.mgr, self.drop = mgr, drop

    async def send_json(self, m):
        if self.mgr and self.drop:      # another task connects/disconnects while we are mid-broadcast
            self.mgr.active_connections.add(object())
            self.mgr.active_connections.discard(self.drop)


def test_broadcast_survives_set_mutation_during_iteration():
    mgr = ConnectionManager()
    a, b = _WS(), _WS()
    a.mgr, a.drop = mgr, b
    mgr.active_connections.update({a, b})
    asyncio.run(mgr.broadcast({"x": 1}))        # used to raise "Set changed size during iteration"


# ---- alerts ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url,ok", [
    ("https://hooks.example.com/x", True), ("http://localhost:9000/hook", True), ("http://webhook-sink:8080/", True),
    ("http://169.254.169.254/latest/meta-data", False), ("http://[fe80::1]/x", False), ("http://metadata.google.internal/", False),
    ("file:///etc/passwd", False), ("ftp://x/y", False), ("not a url", False), ("", False),
])
def test_validate_webhook_url(url, ok):
    if ok:
        assert validate_webhook_url(url) == url
    else:
        with pytest.raises(ValueError):
            validate_webhook_url(url)


def _rule(name="r"):
    return AlertRule(name=name, type="span_error", webhook_url="http://localhost:9/hook")


def test_add_rule_rejects_bad_url():
    with pytest.raises(ValueError):
        AlertManager().add_rule(AlertRule(name="x", type="span_error", webhook_url="http://169.254.169.254/"))


@pytest.mark.asyncio
async def test_webhooks_do_not_block_and_are_rate_limited(monkeypatch):
    sent = []
    release = asyncio.Event()

    async def slow_deliver(self, rule, payload):
        sent.append(payload)
        await release.wait()

    monkeypatch.setattr(AlertManager, "_deliver", slow_deliver)
    m = AlertManager()
    m.rules = [_rule()]
    span = {"status": {"code": "STATUS_CODE_ERROR"}, "serviceName": "s", "name": "n"}   # string code, not 2
    await asyncio.wait_for(asyncio.gather(*[m.check_span_error(span) for _ in range(50)]), timeout=1)   # does not wait on delivery
    await asyncio.sleep(0)
    assert len(sent) == 1                          # one webhook per rule per cooldown window
    assert m._suppressed["r"] == 49
    release.set()
    # after the cooldown the suppressed count is reported
    m._last_sent["r"] -= alerts_mod.WEBHOOK_COOLDOWN_SECONDS + 1
    await m.check_span_error(span)
    await asyncio.sleep(0)
    assert sent[-1]["suppressed_since_last"] == 49
    await asyncio.gather(*m._tasks)


@pytest.mark.asyncio
async def test_numeric_error_status_still_alerts(monkeypatch):
    sent = []

    async def deliver(self, rule, payload):
        sent.append(payload)

    monkeypatch.setattr(AlertManager, "_deliver", deliver)
    m = AlertManager()
    m.rules = [_rule()]
    await m.check_span_error({"status": {"code": 2}})
    await asyncio.sleep(0)
    assert len(sent) == 1


# ---- admin hooks ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_stats_serialises_fractional_percent_and_reset_clears(tmp_path):
    """Regression: /admin/stats 500'd as soon as any metric existed (percent_used is a float, model said int)."""
    import time
    from app.routers import admin
    from tinyolly_common.storage_sqlite import StorageSQLite
    st = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=60)
    st.max_cardinality = 7
    await st.store_metrics([{"name": "m", "type": "gauge", "value": 1, "timestamp": time.time()}])
    stats = await admin.admin_stats(storage=st)
    assert stats["cardinality"]["percent_used"] == pytest.approx(14.29)
    from models import AdminStatsResponse
    AdminStatsResponse(**stats)                       # the response model must accept it
    out = await admin.admin_reset(storage=st)
    assert out["removed"]["metrics_series"] == 1
    assert (await st.get_metric_names()) == []
