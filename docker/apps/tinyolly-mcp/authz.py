"""Draft a least-privilege Istio AuthorizationPolicy from observed callers."""


def build_policy(service: str, namespace: str, callers: list[dict]) -> str | None:
    """Return the YAML text of an ALLOW AuthorizationPolicy for `service` allowing the observed
    callers' SPIFFE identities, or None when no caller has a usable identity."""
    principals = []
    for c in callers or []:
        p = (c.get("principal") or "").strip()
        if p.startswith("spiffe://"):
            p = p[len("spiffe://"):]
        if p and p not in principals:
            principals.append(p)
    if not principals:
        return None
    principals = sorted(principals)
    lines = [
        "apiVersion: security.istio.io/v1",
        "kind: AuthorizationPolicy",
        "metadata:",
        f"  name: {service}-allow-observed-callers",
        f"  namespace: {namespace}",
        "spec:",
        "  selector:",
        "    matchLabels:",
        f"      app: {service}",
        "  action: ALLOW",
        "  rules:",
        "  - from:",
        "    - source:",
        "        principals:",
    ]
    for p in principals:
        lines.append(f'        - "{p}"')
    return "\n".join(lines)


def _growth(series: dict) -> int:
    """Growth of one cumulative series: last value minus first value over its valued datapoints
    (0 if fewer than 2; never negative)."""
    vals = [p["value"] for p in series.get("datapoints", []) if p.get("value") is not None]
    if len(vals) < 2:
        return 0
    return max(0, int(vals[-1] - vals[0]))


def summarize_callers(series: list[dict] | None) -> dict:
    """Split the callers of a service into mTLS (identity-based) and plaintext callers, counting
    the growth of each over the window. Returns {"namespace", "mtls", "plaintext"}."""
    if not series:
        return {"namespace": "default", "mtls": [], "plaintext": []}

    namespace = ""
    mtls: dict[str, dict] = {}
    plaintext: dict[str, dict] = {}

    for s in series:
        attrs = s.get("attributes") or {}
        growth = _growth(s)
        # A caller is seen if its connection counter ever went above zero: long-lived (gRPC) connections stay flat.
        if growth == 0 and not any((p.get("value") or 0) > 0 for p in s.get("datapoints", [])):
            continue
        svc = attrs.get("source_canonical_service") or ""
        if not namespace and attrs.get("destination_workload_namespace"):
            namespace = attrs["destination_workload_namespace"]
        if attrs.get("connection_security_policy") == "mutual_tls" and attrs.get("source_principal"):
            g = mtls.setdefault(svc, {"service": svc, "principal": attrs["source_principal"], "calls": 0})
            g["calls"] += growth
        else:
            g = plaintext.setdefault(svc, {"service": svc, "namespace": attrs.get("source_workload_namespace") or "", "calls": 0})
            g["calls"] += growth

    mtls_list = sorted(mtls.values(), key=lambda g: -g["calls"])
    plaintext_list = sorted(plaintext.values(), key=lambda g: -g["calls"])
    return {"namespace": namespace or "default", "mtls": mtls_list, "plaintext": plaintext_list}
