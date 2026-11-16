"""Compare Istio request metrics before and after a change marker."""


def delta_between(s: dict, start: float, end: float) -> float:
    """Increase of one cumulative series between start and end (inclusive), like Prometheus increase():
    a drop in value is a counter reset (a restart), so the new value counts as growth from zero."""
    pts = [p["value"] for p in s.get("datapoints", [])
           if start <= p["timestamp"] <= end and p.get("value") is not None]
    return sum(v - prev if v >= prev else v for prev, v in zip(pts, pts[1:], strict=False))


def compare_around(series: list[dict] | None, ts: float, window_s: float, now: float | None = None) -> list[dict]:
    """Group series by destination service, compare before/after windows around ts, return changed services."""
    if not series:
        return []

    by_service: dict[str, list[dict]] = {}
    for s in series:
        attrs = s.get("attributes") or {}
        svc = attrs.get("destination_canonical_service")
        if not svc:
            continue
        by_service.setdefault(svc, []).append(s)

    after_end = ts + window_s
    if now is not None:
        after_end = min(after_end, now)

    results = []
    for svc, ss in by_service.items():
        before_requests = 0
        before_failures = 0
        before_flags: dict[str, float] = {}
        after_requests = 0
        after_failures = 0
        after_flags: dict[str, float] = {}

        for s in ss:
            attrs = s.get("attributes") or {}
            flag = attrs.get("response_flags") or ""
            code = str(attrs.get("response_code") or "")
            is_failure = (flag not in ("-", "")) or code.startswith("5")

            b_delta = delta_between(s, ts - window_s, ts)
            a_delta = delta_between(s, ts, after_end)

            before_requests += b_delta
            after_requests += a_delta

            if is_failure:
                before_failures += b_delta
                after_failures += a_delta

            if flag not in ("-", ""):
                if b_delta > 0:
                    before_flags[flag] = before_flags.get(flag, 0) + b_delta
                if a_delta > 0:
                    after_flags[flag] = after_flags.get(flag, 0) + a_delta

        before_pct = round(100 * before_failures / before_requests, 1) if before_requests else 0.0
        after_pct = round(100 * after_failures / after_requests, 1) if after_requests else 0.0

        pct_diff = abs(after_pct - before_pct)
        flags_changed = set(before_flags.keys()) != set(after_flags.keys())
        req_changed = False
        if before_requests > 0 and after_requests >= 2 * before_requests:
            req_changed = True
        elif after_requests > 0 and after_requests <= before_requests / 2:
            req_changed = True
        elif before_requests == 0 and after_requests >= 10:
            req_changed = True

        if not (pct_diff >= 5 or flags_changed or req_changed):
            continue

        if after_pct > before_pct:
            flags_str = ", ".join(sorted(after_flags.keys())) if after_flags else ""
            summary = f"failures rose from {before_pct}% to {after_pct}%"
            if flags_str:
                summary += f" (flags: {flags_str})"
        elif after_pct < before_pct:
            summary = f"failures fell from {before_pct}% to {after_pct}%"
        else:
            if before_requests > 0 and after_requests > 0:
                ratio = after_requests / before_requests
                if ratio >= 1:
                    summary = f"traffic rose {round(ratio, 1)}x"
                else:
                    summary = f"traffic fell to {round(ratio * 100, 1)}% of before"
            elif after_requests > 0:
                summary = f"traffic appeared: {int(after_requests)} requests after, none before"
            else:
                summary = "traffic stopped"

        results.append({
            "service": svc,
            "before": {"requests": int(before_requests), "failure_pct": before_pct, "flags": before_flags},
            "after": {"requests": int(after_requests), "failure_pct": after_pct, "flags": after_flags},
            "summary": summary,
        })

    results.sort(key=lambda r: (-(r["after"]["failure_pct"] - r["before"]["failure_pct"]),
                                -abs(r["after"]["requests"] - r["before"]["requests"])))
    return results


def _classify(before_requests: float, after_requests: float, before_pct: float, after_pct: float) -> str:
    if before_requests == 0 and after_requests > 0:
        return "new"
    if before_requests > 0 and after_requests == 0:
        return "gone"
    if after_pct - before_pct >= 5:
        return "failures_up"
    if after_pct - before_pct <= -5:
        return "failures_down"
    if after_requests >= 2 * before_requests:
        return "traffic_up"
    if after_requests <= before_requests / 2:
        return "traffic_down"
    return "steady"


_EDGE_ORDER = {"failures_up": 0, "failures_down": 1, "new": 2, "gone": 3,
               "traffic_up": 4, "traffic_down": 5, "steady": 6}


def compare_edges(series: list[dict] | None, ts: float, window_s: float, now: float | None = None) -> list[dict]:
    """Group series by (source, destination) edge, compare before/after windows around ts,
    return every edge with a change class, sorted by class then after requests."""
    if not series:
        return []

    by_edge: dict[tuple[str, str], list[dict]] = {}
    for s in series:
        attrs = s.get("attributes") or {}
        src = attrs.get("source_canonical_service")
        dst = attrs.get("destination_canonical_service")
        if not src or not dst:
            continue
        by_edge.setdefault((src, dst), []).append(s)

    after_end = ts + window_s
    if now is not None:
        after_end = min(after_end, now)

    results = []
    for (src, dst), ss in by_edge.items():
        before_requests = 0
        before_failures = 0
        after_requests = 0
        after_failures = 0

        for s in ss:
            attrs = s.get("attributes") or {}
            flag = attrs.get("response_flags") or ""
            code = str(attrs.get("response_code") or "")
            is_failure = (flag not in ("-", "")) or code.startswith("5")

            b_delta = delta_between(s, ts - window_s, ts)
            a_delta = delta_between(s, ts, after_end)

            before_requests += b_delta
            after_requests += a_delta

            if is_failure:
                before_failures += b_delta
                after_failures += a_delta

        if before_requests == 0 and after_requests == 0:
            continue

        before_pct = round(100 * before_failures / before_requests, 1) if before_requests else 0.0
        after_pct = round(100 * after_failures / after_requests, 1) if after_requests else 0.0

        results.append({
            "source": src,
            "target": dst,
            "before": {"requests": int(before_requests), "failure_pct": before_pct},
            "after": {"requests": int(after_requests), "failure_pct": after_pct},
            "change": _classify(before_requests, after_requests, before_pct, after_pct),
        })

    results.sort(key=lambda r: (_EDGE_ORDER[r["change"]], -r["after"]["requests"]))
    return results
