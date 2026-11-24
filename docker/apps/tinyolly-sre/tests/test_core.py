import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["WARMUP_SECONDS"] = "0"; os.environ["INCIDENT_SETTLE_SECONDS"] = "0"
from sre import core
from sre.backend import Backend, Signal
from sre.backends.tinyolly import _is_error


class Fake(Backend):
    name = "fake"
    def detect(self): return []
    def evidence(self, *a, **k): return "e", "svc", "a" * 32


def agent(monkeypatch=None):
    a = core.Agent(Fake()); a.started = 0; return a


def test_parse_final():
    assert core.parse_final('```json\n{"summary": "%s"}\n```' % ("x" * 40))
    assert core.parse_final('{"summary": "short"}') is None


def test_signals_group_into_one_incident(monkeypatch):
    a = agent(); monkeypatch.setattr(a, "run", lambda *x, **k: {"service": "svc", "summary": "s"})
    s = Signal("errors", "cart", "cart failing")
    a.add_signal(s); a.add_signal(s)
    assert len(a.incidents) == 1


def test_incident_resolves_after_quiet_polls(monkeypatch):
    a = agent(); calls = []; monkeypatch.setattr(a, "run", lambda *x, **k: calls.append(x) or {"service": "cart", "summary": "s"})
    s = Signal("errors", "cart", "cart failing")
    a.tick([s]); time.sleep(0.2); a.tick([s]); a.tick([]); a.tick([]); time.sleep(0.3)
    assert not a.incidents[0]["open"] and len(calls) == 3   # investigation + runbook + recovery check


def test_is_error():
    assert _is_error({"status": {"code": 2}})
    assert _is_error({"attributes": [{"key": "http.status_code", "value": {"intValue": 503}}]})
    assert not _is_error({"status": {"code": 0}})


def test_catalog_detectors_need_learned_baseline_then_confirm():
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend()
    ok = {"name": "cart", "rate": 5, "duration_p95": 50, "error_rate": 0.5}
    for _ in range(8): assert not b._catalog_signals({"cart": ok}, {"latency", "traffic", "error-rate"})
    slow = {**ok, "duration_p95": 900}
    assert not b._catalog_signals({"cart": slow}, {"latency"})            # one poll is not enough
    sig = b._catalog_signals({"cart": slow}, {"latency"})
    assert [s.kind for s in sig] == ["latency"] and sig[0].entity == "cart"
    for _ in range(2): sig = b._catalog_signals({"cart": {**ok, "rate": 0.1}}, {"traffic"})
    assert [s.kind for s in sig] == ["traffic"]


def test_vanished_service():
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend(); ok = {"name": "cart", "rate": 5, "duration_p95": 50, "error_rate": 0}
    for _ in range(8): b._catalog_signals({"cart": ok, "web": {**ok, "name": "web"}}, {"vanished"})
    sig = []
    for _ in range(3): sig = b._catalog_signals({"web": {**ok, "name": "web"}}, {"vanished"})
    assert [(s.kind, s.entity) for s in sig] == [("vanished", "cart")]


def test_review_note_is_published_with_verdict(monkeypatch):
    a = agent(); pub = []
    a.b.publish = lambda *x: pub.append(x); a.b.review_evidence = lambda *x: "ev"
    monkeypatch.setattr(core, "chat", lambda *a_, **k: ({"content": "VERDICT: watch\ncart p95 is up"}, "stop", {}))
    f = a.run("review: shift-note", duty="shift-note")
    assert f["verdict"] == "watch" and pub[0][0] == "ai-review" and "VERDICT" not in f["summary"]
