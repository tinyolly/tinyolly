"""Decode Envoy and ztunnel response flags."""

FLAGS: dict[str, tuple[str, str]] = {
    "UH": ("no healthy upstream", "check the destination service has healthy endpoints in the service registry"),
    "UF": ("upstream connection failure", "the upstream refused or failed to accept the connection: check the destination pod is listening and ready"),
    "UO": ("upstream overflow", "the upstream connection pool is exhausted: check connection pool limits and upstream capacity"),
    "NR": ("no route configured", "no route matched the request: check VirtualService routes and hostnames"),
    "URX": ("retry limit exceeded", "all retry attempts were exhausted: check retry policy and upstream health"),
    "UC": ("upstream connection termination", "the upstream closed the connection: check the destination pod is listening and ready"),
    "UT": ("upstream request timeout", "a timeout cut the request: look at route timeouts and destination latency"),
    "LR": ("local reset", "the local proxy reset the connection: check local proxy logs and resource limits"),
    "UR": ("upstream remote reset", "the upstream sent a reset: check the destination service for connection resets"),
    "DC": ("downstream connection termination", "the downstream (client) closed the connection: check client-side timeouts and network"),
    "DI": ("delay injected", "an injected delay, check for a fault-injection VirtualService"),
    "FI": ("fault injected", "a fault was injected, check for a fault-injection VirtualService"),
    "RL": ("rate limited", "the request was rate limited: check the rate limit configuration"),
    "UAEX": ("unauthorized by external authorization", "an external authorization service denied the request: check the authorization policy"),
    "RLSE": ("rate limit service error", "the rate limit service was unreachable: check the rate limit service health"),
    "SI": ("stream idle timeout", "the stream was idle and timed out: check stream idle timeout settings"),
    "DPE": ("downstream protocol error", "a protocol error from the downstream: check client protocol compliance"),
    "UPE": ("upstream protocol error", "a protocol error from the upstream: check upstream protocol compliance"),
    "NC": ("no cluster", "no cluster matched the request: check cluster configuration"),
    "OM": ("overload manager terminated the request", "the proxy is shedding load: check proxy CPU and memory pressure and the overload manager settings"),
    "DF": ("DNS resolution failed", "the destination name did not resolve: check the service name, ServiceEntry and cluster DNS"),
    "DT": ("max duration timeout", "the request or connection hit a maximum duration limit: check max stream and connection duration settings"),
    "LH": ("local service failed health check", "the proxy marked the local service unhealthy: check its health check endpoint"),
    "DENY": ("connection refused by policy", "a connection was refused by policy: check STRICT mTLS or AuthorizationPolicy"),
}


def decode_flags(value: str | None) -> list[dict]:
    """Decode a comma-separated response flags string into a list of {flag, meaning, hint} dicts."""
    if value is None or value == "" or value == "-":
        return []
    out = []
    for raw in value.split(","):
        flag = raw.strip()
        if not flag:
            continue
        meaning, hint = FLAGS.get(flag, ("unknown flag", "see the Envoy response flags reference"))
        out.append({"flag": flag, "meaning": meaning, "hint": hint})
    return out


def summarize_flags(series: list[dict] | None) -> dict:
    """Summarize response flags from a metrics query series list.

    Returns {"total": int, "flags": [{"flag", "count", "share_pct", "meaning", "hint"}]}.
    """
    if not series:
        return {"total": 0, "flags": []}

    counts: dict[str, int] = {}
    for s in series:
        flag = (s.get("attributes") or {}).get("response_flags")
        if flag is None or flag == "":
            flag = "-"
        pts = [p["value"] for p in s.get("datapoints", []) if p.get("value") is not None]
        if len(pts) < 2:
            continue
        delta = max(0, pts[-1] - pts[0])
        counts[flag] = counts.get(flag, 0) + delta

    total = sum(counts.values())
    if total == 0:
        return {"total": 0, "flags": []}

    flags_out = []
    for flag, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        if flag == "-" or count <= 0:
            continue
        if "," in flag:
            parts = [p.strip() for p in flag.split(",") if p.strip()]
            meanings = []
            for p in parts:
                m, _ = FLAGS.get(p, ("unknown flag", "see the Envoy response flags reference"))
                meanings.append(m)
            meaning = "; ".join(meanings)
            hint = FLAGS.get(parts[0], ("", "see the Envoy response flags reference"))[1]
        else:
            meaning, hint = FLAGS.get(flag, ("unknown flag", "see the Envoy response flags reference"))
        flags_out.append({
            "flag": flag,
            "count": count,
            "share_pct": round(count / total * 100, 1),
            "meaning": meaning,
            "hint": hint,
        })

    return {"total": total, "flags": flags_out}
