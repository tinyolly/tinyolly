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
    assert not a.incidents[0]["open"] and len(calls) == 2   # investigation + recovery check (runbook off by default)


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


def test_caller_and_callee_make_one_incident_rooted_at_the_deepest(monkeypatch):
    a = agent(); a.b.topology = lambda: {("frontend", "checkout"), ("checkout", "payment"), ("frontend", "ad")}
    a.add_signal(Signal("error-rate", "checkout", "checkout errors")); a.add_signal(Signal("error-rate", "payment", "payment errors"))
    a.add_signal(Signal("latency", "email", "email slow"))                      # unrelated
    assert len(a.incidents) == 2 and a._deepest(a.incidents[0]) == "payment"
    r = a.records()[-1]
    assert r["symptoms"] == ["checkout errors", "payment errors"] and "frontend" in r["blast_radius"]


def test_investigation_record_lifecycle(monkeypatch):
    a = agent()
    done = {"service": "cart", "summary": "s", "trace": "a" * 32, "status": "ok", "root_cause": "rc", "confidence": "high", "suggested_fixes": []}
    monkeypatch.setattr(a, "run", lambda *x, **k: {"summary": "Recovered: yes, quiet"} if x[2:3] == (True,) else done)
    s = Signal("errors", "cart", "cart failing")
    a.tick([s]); time.sleep(0.2)
    assert a.records()[0]["state"] == "concluded" and a.records()[0]["root_cause"] == "rc"
    a.tick([]); a.tick([]); time.sleep(0.2)
    r = a.records()[0]
    assert r["state"] == "resolved" and r["recovered"] == "yes" and r["ttr_s"] is not None


def test_structured_fixes_are_only_ever_proposed():
    out = core.structured({"confidence": "certain", "suggested_fixes": [{"action": "restart", "status": "applied"}, "junk", {}] + [{"action": "x"}] * 5})
    assert out["confidence"] == "low" and len(out["suggested_fixes"]) == 3
    assert {f["status"] for f in out["suggested_fixes"]} == {"proposed"}


def test_tool_cap_still_ends_ok_with_a_forced_answer(monkeypatch):
    a = agent(); a.b.mcp_url = ""
    many = [{"id": str(i), "function": {"name": "t", "arguments": "{}"}} for i in range(core.MAX_CALLS + 1)]
    replies = iter([{"tool_calls": many}, {"content": '{"summary": "%s", "confidence": "high"}' % ("x" * 40)}])
    monkeypatch.setattr(core, "chat", lambda *a_, **k: (next(replies), "stop", {}))
    f = a.run("incident")
    assert f["status"] == "ok" and f["confidence"] == "high"


def test_tinyolly_services_ignored_and_polluted_baseline_still_alerts():
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend(); ok = {"name": "payment", "rate": 5, "duration_p95": 50}
    for _ in range(8): b._catalog_signals({"payment": {**ok, "error_rate": 19}}, {"error-rate"})
    for _ in range(2): sig = b._catalog_signals({"payment": {**ok, "error_rate": 40}, "tinyolly-ui": {**ok, "name": "tinyolly-ui"}}, {"error-rate"})
    assert [s.entity for s in sig] == ["payment"] and "tinyolly-ui" not in b.learned


def test_span_api_fields_and_error_rate_clears_when_recent_spans_are_healthy(monkeypatch):
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend(); now = time.time_ns()
    span = {"service_name": "payment", "trace_id": "a" * 32, "start_time": now, "name": "Charge", "status": {"code": "STATUS_CODE_ERROR", "message": "bad token"}}
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: [span] * 12 if path == "/api/spans" else default)
    text, svc, tid = b.evidence("t", "payment")
    assert svc == "payment" and tid == "a" * 32 and "bad token" in text
    assert [s.kind for s in b.detect() if s.entity == "payment"] == ["errors"]
    ok = {"name": "payment", "rate": 5, "duration_p95": 50, "error_rate": 0}
    for _ in range(8): b._catalog_signals({"payment": ok}, {"error-rate"}, {})
    stale = {"payment": {**ok, "error_rate": 28}}
    for _ in range(3): sig = b._catalog_signals(stale, {"error-rate"}, {"payment": 0})
    assert not sig


def test_console_pages_and_config_are_served():
    import threading, httpx
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), core.make_handler(agent()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        for path, needle in (("/", "AI SRE Agent"), ("/console.css", "--bg-body"), ("/console.js", "EventSource")):
            assert needle in httpx.get(base + path).text
        assert "links" in httpx.get(base + "/api/config").json()
        assert httpx.get(base + "/../core.py").status_code == 404 and httpx.get(base + "/nope").status_code == 404
    finally: srv.shutdown()


def test_low_traffic_service_error_rate_uses_wider_window(monkeypatch):
    from sre.backends import tinyolly as T
    b = T.TinyOllyBackend(); now = time.time()
    def sp(svc, age, err): return {"service_name": svc, "start_time": int((now - age) * 1e9), "status": {"code": "STATUS_CODE_ERROR" if err else "STATUS_CODE_OK"}}
    # payment at 50% failure but ~1 call / 15 s: 2 errors of 6 in 120 s (under the 3-error floor), 4 of 25 in 360 s
    spans = [sp("payment", a, a in (30, 90)) for a in (10, 30, 50, 70, 90, 110)] + [sp("payment", 130 + 12 * i, i in (1, 5)) for i in range(19)]
    spans += [sp("frontend", i % 100, False) for i in range(200)] + [sp("frontend", 50, True)] * 3   # busy service keeps the short window
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: spans if path == "/api/spans" else default)
    pct = b._recent_error_pct()
    assert pct["payment"] == 16.0 and 0 < pct["frontend"] < 2


def test_new_kind_of_symptom_reinvestigates_once(monkeypatch):
    a = agent(); calls = []; monkeypatch.setattr(a, "run", lambda *x, **k: calls.append(x[0]) or {"service": "payment", "summary": "s"})
    t = Signal("traffic", "payment", "payment: traffic low")
    a.tick([t]); time.sleep(0.2)
    a.tick([t, Signal("error-rate", "payment", "payment: error rate 16%")]); a.tick([t]); time.sleep(0.2)   # errors join a traffic incident -> again
    a.tick([t, Signal("latency", "payment", "payment: p95 up")]); a.tick([t]); time.sleep(0.2)              # not an error kind: no re-run
    assert len(calls) == 2 and "error rate" in calls[1]
    assert a.records()[0]["reinvestigated_at"]


def test_held_traffic_drop_becomes_new_normal_but_errors_never_do():
    from sre.backends import tinyolly as T
    b = T.TinyOllyBackend()
    boot = {"name": "payment", "rate": 0.7, "duration_p95": 50, "error_rate": 0}
    for _ in range(8): b._catalog_signals({"payment": boot}, {"traffic", "error-rate"}, {})
    low = {**boot, "rate": 0.06}
    kinds = [[s.kind for s in b._catalog_signals({"payment": low}, {"traffic"}, {})] for _ in range(T.HOLD_MAX_POLLS + 15)]
    assert kinds[3] == ["traffic"] and kinds[-1] == []                 # fired, then re-baselined and cleared
    bad = {**low, "error_rate": 30}
    errs = [[s.kind for s in b._catalog_signals({"payment": bad}, {"error-rate"}, {"payment": 30})] for _ in range(T.HOLD_MAX_POLLS + 15)]
    assert errs[-1] == ["error-rate"]                                  # an outage stays an outage


def test_recent_stats_rate_p95_and_fence(monkeypatch):
    from sre.backends import tinyolly as T
    monkeypatch.setattr(T, "RECENT_STATS", True); monkeypatch.setattr(T, "RECENT_S", 30)
    b = T.TinyOllyBackend(); now = time.time()
    fast = [{"service_name": "shipping", "start_time": int((now - i) * 1e9), "duration_ms": 20, "status": {}} for i in range(30)]
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: fast if path == "/api/spans" else default)
    st = b._recent_stats()["shipping"]
    assert abs(st["rate"] - 1.0) < 0.05 and st["duration_p95"] == 20
    cat = {"shipping": {"name": "shipping", "rate": 99, "duration_p95": 999, "error_rate": 0}}      # catalog long average ignored
    for _ in range(8): assert b._catalog_signals(cat, {"latency", "traffic"}, b._recent_stats()) == []
    slow = [{**s, "duration_ms": 10000} for s in fast]
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: slow if path == "/api/spans" else default)
    kinds = [[x.kind for x in b._catalog_signals(cat, {"latency"}, b._recent_stats())] for _ in range(3)]
    assert kinds[-1] == ["latency"]                                                                # p95 jump seen at once
    b.fence(now); assert all(not L.hits for L in b.learned.values())
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: [] if path == "/api/spans" else default)
    assert b._catalog_signals(cat, {"traffic"}, b._recent_stats()) == []                          # empty right after a fence: no false drop


def test_op_errors_finds_failing_call_inside_busy_service(monkeypatch):
    from sre.backends import tinyolly as T
    b = T.TinyOllyBackend(); now = time.time()
    def mk(fail):
        rows = [{"service_name": "frontend", "name": "GET", "start_time": int((now - i % 100) * 1e9), "status": {}} for i in range(600)]
        rows += [{"service_name": "frontend", "name": "GetAds", "start_time": int((now - i * 5) * 1e9),
                  "status": {"code": "STATUS_CODE_ERROR" if fail and i % 4 == 0 else "STATUS_CODE_OK"}} for i in range(30)]
        return rows
    data = {"spans": mk(False)}
    monkeypatch.setattr(b, "_safe", lambda path, default, **k: data["spans"] if path == "/api/spans" else default)
    for _ in range(T.BASELINE_POLLS + 1): assert b._op_signals() == []
    data["spans"] = mk(True)                                  # 8 of 30 GetAds fail: 1.3% of all frontend spans, 27% of the call
    sig = [b._op_signals() for _ in range(T.CONFIRM_POLLS)][-1]
    assert [s.kind for s in sig] == ["op-errors"] and "GetAds failing 27%" in sig[0].text


def test_verdict_theories_trail_timeline_and_postmortem(monkeypatch):
    s = core.structured({"confidence": "high", "verdict": "act now", "hypotheses": [{"claim": "a deploy", "status": "ruled out", "evidence": "no deploy marker"},
                         {"claim": "paymentFailure flag", "status": "confirmed", "evidence": "flag flipped 1 min before errors"}, {"x": 1}]})
    assert s["verdict"] == "act_now" and s["would_page"] and [t["status"] for t in s["theories"]] == ["ruled_out", "confirmed"]
    assert core.structured({"confidence": "low"})["verdict"] == "watch"                       # missing verdict: no page unless high
    a = agent()
    final = '{"summary": "payment rejects charges since the flag flip; fix: flag off", "root_cause": "paymentFailure=50%", "confidence": "high", "verdict": "act_now", "suggested_fixes": [{"action": "turn paymentFailure off"}]}'
    class M:
        def tools(self): return [{"name": "query_logs", "inputSchema": {"type": "object", "properties": {}}}]
        def call(self, fn, args): return "payment: Invalid token x3"
    a.b.local_tools = M()
    replies = iter([({"content": "", "tool_calls": [{"id": "1", "function": {"name": "query_logs", "arguments": '{"service": "payment"}'}}]}, "tool_calls", {}),
                    ({"content": final}, "stop", {}),
                    ({"content": "### Summary\nCheckout failed for 3 minutes.\n### Five whys\n1. flag on\n2. no guard\n### Prevention\n- alert on flag flips"}, "stop", {})])
    monkeypatch.setattr(core, "chat", lambda *a_, **k: next(replies))
    a.b.changes = lambda m=30: [{"title": "flag paymentFailure: off -> 50%", "timestamp": time.time() - 30},
                                 {"title": "flag cartFailure: off -> 75%", "timestamp": time.time() - 20}]        # unrelated: must not appear
    a.add_signal(Signal("errors", "payment", "payment failing")); inc = a.incidents[0]; inc["investigated"] = True
    a._investigate(inc, "incident 1: payment failing")
    r = a.records()[0]
    assert r["trail"][0]["tool"] == "query_logs" and r["trail"][0]["args"] == {"service": "payment"} and "Invalid token" in r["trail"][0]["result"]
    kinds = [e["kind"] for e in r["timeline"]]
    assert kinds[0] == "change" and {"detected", "investigation", "concluded", "fix"} <= set(kinds)     # the change sorts first: cause before symptom
    assert [e["text"] for e in r["timeline"] if e["kind"] == "change"] == ["Change: flag paymentFailure: off -> 50%"]
    md = a.postmortem(1)
    assert "# Postmortem: svc: paymentFailure=50%" in md and "payment failing" in r["symptoms"] and "1. flag on" in md and "| Time | Event |" in md and "query_logs(service=payment)" in md
    assert "- [ ] alert on flag flips" in md and a.postmortem(1) == md                         # cached: no second model call


def test_concluded_record_is_titled_by_cause_and_reaches_questions(monkeypatch):
    a = agent()
    done = {"service": "payment", "summary": "s", "status": "ok", "title": "", "root_cause": "Charge rejects the token. More."}
    monkeypatch.setattr(a, "run", lambda *x, **k: done)
    a.tick([Signal("errors", "frontend", "frontend failing")]); time.sleep(0.2)
    r = a.records()[0]
    assert r["title"] == "payment: Charge rejects the token." and r["symptoms"] == ["frontend failing"]
    assert "concluded" in a.incident_lines() and r["title"] in a.incident_lines()


def test_late_traffic_drop_joins_the_callers_error_incident(monkeypatch):
    a = agent(); a.b.topology = lambda: {("checkout", "email")}
    a.add_signal(Signal("errors", "checkout", "checkout failing"), now=1000)
    a.add_signal(Signal("latency", "email", "email slow"), now=2000)              # other kinds keep the age limit
    assert len(a.incidents) == 2
    a.incidents.pop()
    a.add_signal(Signal("traffic", "email", "email quiet"), now=2000)
    assert len(a.incidents) == 1 and "email" in a.incidents[0]["entities"]


def _sp(i, parent, svc, bad=True):
    return {"spanId": i, "parentSpanId": parent, "serviceName": svc, "name": i, "status": {"code": 2} if bad else {}}


def test_errors_are_attributed_to_where_they_start():
    from sre.backends.tinyolly import failure_origins
    got = failure_origins([_sp("a", None, "frontend"), _sp("b", "a", "checkout"), _sp("c", "b", "payment"), _sp("d", "b", "cart", False)])
    assert sorted((s, o) for s, _, o in got) == [("checkout", "payment"), ("frontend", "payment"), ("payment", "payment")]


def test_separate_faults_behind_one_caller_stay_separate(monkeypatch):
    a = agent(); a.b.topology = lambda: {("frontend", "ad"), ("frontend", "checkout"), ("checkout", "payment")}
    a.add_signal(Signal("errors", "payment", "frontend failing", via="frontend"))
    a.add_signal(Signal("errors", "ad", "ad failing"))
    a.add_signal(Signal("errors", "payment", "payment failing"))
    assert [sorted(i["entities"]) for i in a.incidents] == [["payment"], ["ad"]]


def test_restart_is_detected_across_split_series_and_gets_its_own_incident(monkeypatch):
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend(); now = time.time()
    res = {"service.name": "email", "k8s.pod.uid": "p"}
    def series(t, v, reason=""): return {"resource": {**res, "k8s.container.status.last_terminated_reason": reason}, "datapoints": [{"timestamp": t, "value": v}]}
    b._safe = lambda path, default, **k: {"series": [series(now - 60, 0), series(now - 5, 2, "OOMKilled")]} if path.endswith("restarts") else default
    sig = b._restart_signals()
    assert [s.text for s in sig] == ["email: container restarted 2 time(s) in the last 10 min (last exit: OOMKilled)"]
    a = agent(); a.add_signal(Signal("errors", "payment", "payment failing"))
    a.incidents[0]["entities"].add("email")
    a.add_signal(sig[0])
    assert len(a.incidents) == 2


def test_cpu_spike_and_brief_health_failures_are_not_signals():
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend(); now = time.time()
    def cpu(*v): return {"series": [{"resource": {"service.name": "ad"}, "datapoints": [{"timestamp": now - 60 * (len(v) - i), "value": x} for i, x in enumerate(v)]}]}
    b._safe = lambda path, default, **k: cpu(0.01, 0.9, 0.9) if "jvm" in path else default
    assert not b._cpu_signals()
    b._safe = lambda path, default, **k: cpu(0.5, 0.5, 0.5) if "jvm" in path else default
    assert [s.entity for s in b._cpu_signals()] == ["ad"]
    def logs(step): return [{"service_name": "cart", "severity": "Error", "message": "Health check failed", "timestamp": now - i * step} for i in range(7)]
    b._safe = lambda *a, **k: logs(5)
    assert not b._health_signals()
    b._safe = lambda *a, **k: logs(30)
    assert [s.entity for s in b._health_signals()] == ["cart"]


def test_evidence_never_borrows_another_services_trace_or_logs():
    from sre.backends.tinyolly import TinyOllyBackend
    b = TinyOllyBackend()
    span = {"service_name": "payment", "trace_id": "a" * 32, "start_time": time.time(), "name": "charge", "status": {"code": 2}}
    log_ = {"service_name": "cart", "severity": "Error", "message": "Health check failed", "timestamp": time.time()}
    b._safe = lambda path, default, **k: [span] if path == "/api/spans" else [log_] if path == "/api/logs" else default
    text, svc, tid = b.evidence("cart: health check failing", "cart")
    assert svc == "cart" and not tid and "cart: Health check failed" in text
