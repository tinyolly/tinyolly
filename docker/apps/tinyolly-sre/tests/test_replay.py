import json, os, subprocess, sys, time
HERE = os.path.dirname(__file__)


def span(i, t, svc, err):
    return {"span_id": f"s{i}", "trace_id": "a" * 32, "name": "Charge", "start_time": int(t * 1e9), "service_name": svc,
            "status": {"code": "STATUS_CODE_ERROR" if err else "STATUS_CODE_OK"}}


def test_replay_detects_recorded_fault_and_grades_it(tmp_path):
    t0, lines, n = time.time() - 3600, [], 0
    for p in range(60):                                        # 10 s polls; payment fails from poll 30 to 45
        t = t0 + 10 * p; fault = 30 <= p < 45; delta = []
        for k in range(6):
            n += 1; delta.append(span(n, t - k, "payment", fault and k % 2 == 0))
        cat = [{"name": "payment", "rate": 0.6, "duration_p95": 50, "error_rate": 0}]
        lines.append({"t": t, "scenario": "payment-degraded" if fault else None, "flags": {"paymentFailure": "50%"} if fault else None,
                      "expected": {"service": "payment", "cause_keywords": ["payment"], "detector": "errors"} if fault else None,
                      "r": {"/api/spans?limit=5000": {"delta": delta}, "/api/service-catalog?": cat}})
    f = tmp_path / "rec.jsonl"; f.write_text("\n".join(json.dumps(l) for l in lines))
    env = {**os.environ, "WARMUP_SECONDS": "0", "BASELINE_POLLS": "6", "DETECT_SECONDS": "10", "INCIDENT_SETTLE_SECONDS": "15", "DETECT_RECENT_SECONDS": "45"}
    out = subprocess.run([sys.executable, "-B", "-m", "sre.replay", str(f), "--timeline"], cwd=os.path.join(HERE, ".."), env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "payment-degraded" in out.stdout and "Missed faults (no incident opened): none" in out.stdout, out.stdout
    assert "false-positive" not in out.stdout.split("|---")[-1], out.stdout


def test_model_replay_routes_tool_calls_to_recorded_data(monkeypatch):
    sys.path.insert(0, os.path.join(HERE, ".."))
    import types
    from sre import core, replay
    from sre.backends import tinyolly as T
    now = time.time(); clock = types.SimpleNamespace(now=now)
    b = types.SimpleNamespace(pool={"spans": {"s1": span(1, now - 5, "payment", True)}, "logs": {}}, changes=lambda m: [{"title": "flag paymentFailure: off -> 50%"}],
                              _safe=lambda *a, **k: [])
    tools = replay.ReplayTools(b, clock, T)
    assert "paymentFailure" in tools.call("what_changed", {}) and '"payment"' in tools.call("search_spans", {"service": "payment", "errors_only": True})

    class Fake(core.Backend):
        name = "fake"; local_tools = tools
        def evidence(self, *a, **k): return "e", "payment", "a" * 32
    replies = iter([({"content": "", "tool_calls": [{"id": "1", "function": {"name": "what_changed", "arguments": "{}"}}]}, "tool_calls", {}),
                    ({"content": '{"summary": "payment fails since the paymentFailure flag went to 50 percent", "cited_service": "payment"}'}, "stop", {})])
    monkeypatch.setattr(core, "chat", lambda *a, **k: next(replies))
    f = core.Agent(Fake()).run("incident 1: payment errors", "payment")
    assert f["status"] == "ok" and f["tool_calls"] == 1 and f["tools_used"] == ["what_changed"]
