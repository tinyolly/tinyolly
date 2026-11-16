"""Score an investigation answer against a ground-truth spec."""
import re


def _matches(text, term):
    low = text.lower()
    if term.isupper() and 1 <= len(term) <= 5:
        return re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE) is not None
    return term.lower() in low


def _any_match(text, terms):
    return any(_matches(text, t) for t in terms)


def grade(answer, tool_calls, truth):
    truth = truth or {}
    answer = answer or ""
    tool_calls = tool_calls or []
    called = {tc.get("name") for tc in tool_calls}

    service = truth.get("service")
    if service is None:
        service_ok = True
    else:
        service_ok = _matches(answer, service)

    if "cause_any" in truth:
        cause_ok = _any_match(answer, truth.get("cause_any") or [])
    else:
        healthy = truth.get("healthy_any") or []
        forbidden = truth.get("forbidden_any") or []
        cause_ok = _any_match(answer, healthy) and not _any_match(answer, forbidden)

    tools_any = truth.get("tools_any") or []
    if not tools_any:
        evidence_ok = True
    else:
        evidence_ok = any(name in tools_any for name in called)

    values = [float(service_ok), float(cause_ok), float(evidence_ok)]
    score = sum(values) / len(values)
    passed = bool(service_ok and cause_ok and evidence_ok)

    return {
        "service_ok": bool(service_ok),
        "cause_ok": bool(cause_ok),
        "evidence_ok": bool(evidence_ok),
        "score": score,
        "passed": passed,
    }
