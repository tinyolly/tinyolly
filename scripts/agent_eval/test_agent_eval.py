"""Tests for the pure parts of the MCP investigation eval: agent loop, tool schema conversion, grading."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agent = load("agent")
grader = load("grader")


def test_mcp_tools_to_ollama_format():
    tools = [{"name": "get_edge", "description": "Drill into an edge", "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]}},
             {"name": "list_services"}]
    out = agent.mcp_tools_to_ollama(tools)
    assert out[0] == {"type": "function", "function": {"name": "get_edge", "description": "Drill into an edge",
                                                       "parameters": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]}}}
    assert out[1]["function"]["name"] == "list_services" and out[1]["function"]["parameters"] == {"type": "object", "properties": {}}
    assert out[1]["function"]["description"] == ""


def tool_reply(name, args):
    return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}}


def text_reply(text):
    return {"message": {"role": "assistant", "content": text}}


def test_run_agent_calls_tools_then_answers():
    replies = iter([tool_reply("get_mesh_posture", {}), tool_reply("get_edge", {"source": "a", "target": "b"}), text_reply("a to b is failing with UC")])
    seen_messages = []

    def chat(messages, tools):
        seen_messages.append([m["role"] for m in messages])
        return next(replies)
    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        return '{"ok": true}'
    out = agent.run_agent("what is wrong?", chat, call_tool, [{"type": "function", "function": {"name": "x"}}], max_steps=6, system="be brief")
    assert out["answer"] == "a to b is failing with UC" and out["steps"] == 3 and out["truncated"] is False
    assert out["tool_calls"] == [{"name": "get_mesh_posture", "args": {}}, {"name": "get_edge", "args": {"source": "a", "target": "b"}}]
    assert calls == [("get_mesh_posture", {}), ("get_edge", {"source": "a", "target": "b"})]
    assert seen_messages[0] == ["system", "user"] and seen_messages[2] == ["system", "user", "assistant", "tool", "assistant", "tool"]


def test_run_agent_truncates_long_tool_results_and_survives_tool_errors():
    replies = iter([tool_reply("big", {}), tool_reply("boom", {}), text_reply("done")])
    captured = []

    def chat(messages, tools):
        captured.append(messages[-1])
        return next(replies)

    def call_tool(name, args):
        if name == "boom":
            raise RuntimeError("tool exploded")
        return "x" * 20000
    out = agent.run_agent("q", chat, call_tool, [], max_steps=5, max_result_chars=1000)
    assert out["answer"] == "done"
    assert len(captured[1]["content"]) <= 1100 and captured[1]["role"] == "tool"
    assert "tool exploded" in captured[2]["content"]


def test_run_agent_stops_at_max_steps():
    def chat(messages, tools):
        return tool_reply("loop", {})
    out = agent.run_agent("q", chat, lambda n, a: "r", [], max_steps=3)
    assert out["truncated"] is True and out["steps"] == 3 and len(out["tool_calls"]) == 3


TRUTH = {"service": "productcatalogservice", "cause_any": ["UC", "connection termination", "upstream closed"], "tools_any": ["get_edge", "what_changed"]}


def test_grade_pass():
    g = grader.grade("The frontend -> productcatalogservice edge shows 50% UC (upstream connection termination).", [{"name": "get_edge", "args": {}}], TRUTH)
    assert g["service_ok"] and g["cause_ok"] and g["evidence_ok"] and g["passed"] and g["score"] == 1.0


def test_grade_partial_and_fail():
    g = grader.grade("Something is slow in the shop.", [{"name": "list_services", "args": {}}], TRUTH)
    assert not g["service_ok"] and not g["cause_ok"] and not g["evidence_ok"] and not g["passed"] and g["score"] == 0.0
    g = grader.grade("productcatalogservice has errors", [{"name": "get_edge", "args": {}}], TRUTH)
    assert g["service_ok"] and not g["cause_ok"] and g["evidence_ok"] and not g["passed"] and round(g["score"], 2) == 0.67


def test_grade_is_case_insensitive_for_words_but_flags_match_whole_tokens():
    assert grader.grade("PRODUCTCATALOGSERVICE: upstream CLOSED the connection", [{"name": "what_changed", "args": {}}], TRUTH)["passed"]
    # "UC" inside another word must not count as the flag
    g = grader.grade("productcatalogservice is succulent", [{"name": "get_edge", "args": {}}], {**TRUTH, "cause_any": ["UC"]})
    assert not g["cause_ok"]


CONTROL = {"service": None, "healthy_any": ["healthy", "no problem", "no issues", "normal"], "forbidden_any": ["UC", "DENY", "outage"], "tools_any": []}


def test_grade_control_scenario():
    assert grader.grade("The mesh looks healthy: all edges are mTLS and error free.", [], CONTROL)["passed"]
    assert not grader.grade("The mesh looks healthy but there is an outage in cart.", [], CONTROL)["passed"]
    assert not grader.grade("I could not tell.", [], CONTROL)["passed"]


def test_run_agent_asks_for_a_final_answer_when_out_of_steps():
    seen = []

    def chat(messages, tools):
        seen.append((messages[-1]["role"], bool(tools)))
        return tool_reply("loop", {}) if tools else text_reply("best guess: svc is failing")
    out = agent.run_agent("q", chat, lambda n, a: "r", [{"type": "function", "function": {"name": "loop"}}], max_steps=2)
    assert out["truncated"] is True and out["answer"] == "best guess: svc is failing"
    assert seen[-1] == ("user", False)
