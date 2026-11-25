import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sre import llm


def test_presets_default_local_and_cloud_only_with_keys(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PRESET", "MODEL"): monkeypatch.delenv(k, raising=False)
    m = llm.Models()
    assert list(m.p) == ["local"] and m.name == "local" and m.model == "qwen3.8:27b-mtp-q4_K_M"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k"); monkeypatch.setenv("OPENAI_API_KEY", "k"); monkeypatch.setenv("LLM_PRESET", "claude")
    m = llm.Models()
    assert set(m.p) == {"local", "openai", "claude"} and m.name == "claude" and m.model == "claude-opus-5-5"
    monkeypatch.setattr(m, "check", lambda *a: "ok")
    m.use("openai"); assert m.name == "openai"
    try: m.use("nope"); assert False
    except KeyError: pass


def test_to_anthropic_groups_tool_results_and_replays_raw():
    tc = [{"id": "t1", "type": "function", "function": {"name": "get_trace", "arguments": '{"id": "x"}'}},
          {"id": "t2", "type": "function", "function": {"name": "list_services", "arguments": ""}}]
    raw = [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "tool_use", "id": "t9", "name": "x", "input": {}}]
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "go"},
            {"role": "assistant", "content": "looking", "tool_calls": tc},
            {"role": "tool", "tool_call_id": "t1", "content": "A"}, {"role": "tool", "tool_call_id": "t2", "content": ""},
            {"role": "assistant", "content": "", "tool_calls": [], "_raw": raw}, {"role": "user", "content": "final"}]
    tools = [{"type": "function", "function": {"name": "get_trace", "description": "d", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}}}}]
    system, out, at = llm.to_anthropic(msgs, tools)
    assert system == "SYS" and [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user"]
    assert out[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "get_trace", "input": {"id": "x"}}
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"] and out[2]["content"][1]["content"] == "(empty)"
    assert out[3]["content"] is raw                         # Claude's own turn comes back unchanged
    assert at == [{"name": "get_trace", "description": "d", "input_schema": tools[0]["function"]["parameters"]}]


def test_openai_transport_strips_raw(monkeypatch):
    seen = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {}}
    monkeypatch.setattr(llm.httpx, "post", lambda url, json, **k: seen.update(url=url, body=json) or R())
    m, fin, _ = llm._openai({"url": "http://x/v1", "key": "", "model": "q"}, [{"role": "assistant", "content": "a", "_raw": [1]}], None, 5)
    assert seen["url"] == "http://x/v1/chat/completions" and "_raw" not in seen["body"]["messages"][0] and m["content"] == "hi"
