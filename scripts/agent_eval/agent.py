"""Tiny tool-calling agent loop and MCP-to-Ollama tool schema conversion."""
import json

DEFAULT_PARAMETERS = {"type": "object", "properties": {}}


def mcp_tools_to_ollama(tools):
    out = []
    for tool in tools:
        name = tool.get("name", "")
        description = tool.get("description", "")
        parameters = tool.get("inputSchema", DEFAULT_PARAMETERS)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
    return out


def _truncate(text, max_result_chars):
    if len(text) > max_result_chars:
        return text[:max_result_chars] + "...[truncated]"
    return text


def run_agent(question, chat, call_tool, tools, max_steps=8, system="", max_result_chars=4000):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": question})

    tool_calls = []
    steps = 0
    last_content = ""

    for _ in range(max_steps):
        reply = chat(messages, tools)
        msg = reply["message"]
        steps += 1

        assistant_msg = {
            "role": "assistant",
            "content": msg.get("content", ""),
            "tool_calls": msg.get("tool_calls"),
        }
        messages.append(assistant_msg)
        last_content = assistant_msg["content"]

        calls = msg.get("tool_calls")
        if not calls:
            return {
                "answer": assistant_msg["content"],
                "tool_calls": tool_calls,
                "steps": steps,
                "truncated": False,
            }

        for call in calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            tool_calls.append({"name": name, "args": args})
            try:
                result = call_tool(name, args)
            except Exception as exc:
                result = "error: " + str(exc)
            if not isinstance(result, str):
                result = json.dumps(result)
            result = _truncate(result, max_result_chars)
            messages.append({"role": "tool", "content": result, "tool_name": name})

    # Out of steps: ask once for a final answer from what was gathered (no tools), so the run can still be graded.
    messages.append({"role": "user", "content": "You are out of steps. Answer now from the evidence you have gathered."})
    final = chat(messages, [])["message"].get("content", "") or last_content
    return {
        "answer": final,
        "tool_calls": tool_calls,
        "steps": steps,
        "truncated": True,
    }
