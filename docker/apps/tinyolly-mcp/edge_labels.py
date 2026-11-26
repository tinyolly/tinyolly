"""Extra text for a service-map edge label on LLM and MCP edges (tokens or tools, then calls blocked at the gateway)."""


def _fmt(n: float) -> str:
    if n < 1000:
        return str(int(round(n)))
    k = n / 1000
    s = f"{k:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s + "k"


def ai_edge_suffix(e: dict) -> str:
    blocked = sum((e.get("blocked") or {}).values())
    return " · ".join(x for x in (_main(e), f"{blocked} blocked" if blocked else "") if x)


def _main(e: dict) -> str:
    tokens = e.get("tokens_in", 0) + e.get("tokens_out", 0)
    if tokens > 0:
        value = e.get("value", 0)
        req_rate = e.get("req_rate", 0)
        if value > 0 and req_rate > 0:
            per_min = tokens / value * req_rate * 60
            return _fmt(per_min) + " tok/min"
        return _fmt(tokens) + " tok"
    tools = e.get("tools")
    if tools:
        busiest = max(tools, key=tools.get)
        others = len(tools) - 1
        if others > 0:
            return f"{busiest} +{others}"
        return busiest
    return ""
