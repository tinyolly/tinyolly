"""journey.py: turn one trace into ordered service hops and a mesh-versus-app time split."""


def is_proxy(name: str) -> bool:
    if name.startswith("waypoint") or name.startswith("ztunnel"):
        return True
    if name.endswith("-istio"):
        return True
    if "ingressgateway" in name or "ingress-gateway" in name:
        return True
    return False


def _to_int(value) -> int:
    return int(value)


def _span_start(span: dict) -> int:
    return _to_int(span["startTimeUnixNano"])


def _span_end(span: dict) -> int:
    return _to_int(span["endTimeUnixNano"])


def _span_duration(span: dict) -> int:
    return _span_end(span) - _span_start(span)


def journey_hops(spans: list) -> list:
    if not spans:
        return []

    by_id = {span["spanId"]: span for span in spans}
    earliest_start = min(_span_start(s) for s in spans)

    indexed = []
    for span in spans:
        parent_id = span.get("parentSpanId")
        if parent_id is None or parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        if parent["serviceName"] == span["serviceName"]:
            continue
        hop = {
            "source": parent["serviceName"],
            "target": span["serviceName"],
            "duration_ms": _span_duration(span) / 1_000_000,
            "start_ms": (_span_start(span) - earliest_start) / 1_000_000,
            "via_proxy": is_proxy(parent["serviceName"]) or is_proxy(span["serviceName"]),
        }
        indexed.append((_span_start(span), span["spanId"], hop))

    indexed.sort(key=lambda x: (x[0], x[1]))
    result = []
    for i, (_, _, hop) in enumerate(indexed, start=1):
        hop["order"] = i
        result.append(hop)
    return result


def mesh_vs_app(spans: list) -> dict:
    if not spans:
        return {"total_ms": 0.0, "proxy_ms": 0.0, "app_ms": 0.0, "proxy_pct": 0.0, "hops": 0}

    earliest_start = min(_span_start(s) for s in spans)
    latest_end = max(_span_end(s) for s in spans)
    total_ms = round((latest_end - earliest_start) / 1_000_000, 1)

    by_id = {span["spanId"]: span for span in spans}

    children = {}
    for span in spans:
        parent_id = span.get("parentSpanId")
        if parent_id is not None and parent_id in by_id:
            children.setdefault(parent_id, []).append(span)

    proxy_ms = 0.0
    for span in spans:
        if not is_proxy(span["serviceName"]):
            continue
        dur = _span_duration(span)
        child_sum = sum(_span_duration(c) for c in children.get(span["spanId"], []))
        self_time = max(0, dur - child_sum)
        proxy_ms += self_time / 1_000_000

    proxy_ms = round(proxy_ms, 1)
    app_ms = round(total_ms - proxy_ms, 1)
    proxy_pct = round(100 * proxy_ms / total_ms, 1) if total_ms > 0 else 0.0

    return {
        "total_ms": total_ms,
        "proxy_ms": proxy_ms,
        "app_ms": app_ms,
        "proxy_pct": proxy_pct,
        "hops": len(journey_hops(spans)),
    }
