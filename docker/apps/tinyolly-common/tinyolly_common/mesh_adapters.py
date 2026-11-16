"""Pure adapters that turn raw telemetry (Istio metric series) into service-graph edges.

No storage imports: these functions take already-fetched data and return plain dicts, so they
are trivially testable and reusable across storage backends.
"""
from typing import Any, Dict, List, Set


def canonical_name(name: str, namespaces: Set[str]) -> str:
    """Strip one trailing `.<ns>` from a proxy/app identity, but only when `<ns>` is a known namespace."""
    if "." in name:
        head, _, tail = name.rpartition(".")
        if tail in namespaces:
            return head
    return name


def node_role(name: str) -> str:
    """Classify a node by its name: waypoint, gateway, ztunnel, or a plain service."""
    if name.startswith("waypoint"):
        return "waypoint"
    if name.endswith("-istio") or "ingress" in name or "gateway" in name:
        return "gateway"
    if name.startswith("ztunnel"):
        return "ztunnel"
    return "service"


def metric_namespaces(series: List[Dict[str, Any]]) -> Set[str]:
    """Collect the non-empty source/destination workload namespaces seen across metric series."""
    out: Set[str] = set()
    for s in series:
        attrs = s.get("attributes", {}) or {}
        for key in ("source_workload_namespace", "destination_workload_namespace"):
            val = attrs.get(key)
            if val:
                out.add(val)
    return out


def merge_graph(graph: Dict[str, Any], namespaces: Set[str]) -> Dict[str, Any]:
    """Return a new graph with node identities merged (`.ns` stripped when known), roles set on every
    node, and parallel edges combined. With empty `namespaces` nothing is renamed but roles are added."""
    # Rename nodes and combine collisions, keeping the one with the larger metrics.span_count.
    nodes: Dict[str, Dict[str, Any]] = {}
    for n in graph.get("nodes", []):
        cid = canonical_name(n["id"], namespaces)
        existing = nodes.get(cid)
        if existing is None:
            nodes[cid] = dict(n)
            continue
        if (n.get("metrics") or {}).get("span_count", 0) > (existing.get("metrics") or {}).get("span_count", 0):
            nodes[cid] = dict(n)

    # Set the role on every node and keep the label in sync with the (possibly renamed) id.
    for cid, n in nodes.items():
        n["id"] = cid
        n["role"] = node_role(cid)
        n["label"] = cid

    # Rename edge endpoints, combine parallel edges, drop self-loops.
    edges: Dict[tuple, Dict[str, Any]] = {}
    for e in graph.get("edges", []):
        s = canonical_name(e["source"], namespaces)
        t = canonical_name(e["target"], namespaces)
        if s == t:
            continue
        key = (s, t)
        existing = edges.get(key)
        if existing is None:
            edges[key] = dict(e)
            continue
        base = existing
        other = e
        if e.get("value", 0) > base.get("value", 0):
            base, other = e, existing
        base["p95"] = max(base.get("p95", 0), other.get("p95", 0))
        base["error_count"] = max(base.get("error_count", 0), other.get("error_count", 0))
        base["denied_count"] = max(base.get("denied_count", 0), other.get("denied_count", 0))
        base["req_rate"] = max(base.get("req_rate", 0), other.get("req_rate", 0))
        if "l7" in base or "l7" in other:
            base["l7"] = bool(base.get("l7")) or bool(other.get("l7"))
        for ck in ("source_cluster", "target_cluster"):
            if base.get(ck) in (None, "") and other.get(ck) not in (None, ""):
                base[ck] = other[ck]
        if base.get("cross_cluster") is None and other.get("cross_cluster") is not None:
            base["cross_cluster"] = other["cross_cluster"]
        elif base.get("cross_cluster") is not None and other.get("cross_cluster") is not None:
            base["cross_cluster"] = bool(base["cross_cluster"]) or bool(other["cross_cluster"])
        if base.get("source_cluster") is None and other.get("source_cluster") is not None:
            base["source_cluster"] = other["source_cluster"]
        if base.get("target_cluster") is None and other.get("target_cluster") is not None:
            base["target_cluster"] = other["target_cluster"]
        kinds = {base.get("source_kind"), other.get("source_kind")}
        if "metrics" in kinds and kinds - {"metrics"}:
            base["source_kind"] = "traces+metrics"
        if base.get("mtls") is None:
            base["mtls"] = other.get("mtls")
        edges[key] = base

    for (s, t), e in edges.items():
        e["source"], e["target"] = s, t
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def _series_count(datapoints: List[Dict[str, Any]]) -> int:
    """Counter delta for one series: last value minus first value (single point: its value), never negative."""
    if not datapoints:
        return 0
    values = [dp.get("value") for dp in datapoints if dp.get("value") is not None]
    if not values:
        return 0
    if len(values) == 1:
        count = values[0]
    else:
        count = values[-1] - values[0]
    return max(int(count), 0)


def metric_edges(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn Istio metric series into service-to-service edges.

    `series` is the output of `get_metric_series` (items have `attributes` and `datapoints` with
    `timestamp`/`value`). For one (source, target) pair the count is the MAX across series (both
    reporters and L4/L7 series see the same traffic; never sum), `mtls` is True only if every
    series for the pair is mutual TLS, and `errors` sums the counts of series whose response code
    starts with "5".
    """
    pairs: Dict[tuple, Dict[str, Any]] = {}

    for s in series:
        attrs = s.get("attributes", {}) or {}
        source = attrs.get("source_canonical_service") or attrs.get("source_workload") or ""
        target = attrs.get("destination_canonical_service") or attrs.get("destination_workload") or ""
        # A request that never reached an upstream (waypoint local reply) has no destination workload;
        # fall back to the service it was addressed to.
        unreached = target in ("", "unknown")
        if unreached:
            target = attrs.get("destination_service_name") or ""
        if not source or not target or source == "unknown" or target == "unknown":
            continue

        count = _series_count(s.get("datapoints", []))
        is_mtls = attrs.get("connection_security_policy") == "mutual_tls"
        src_cluster = attrs.get("source_cluster")
        dst_cluster = attrs.get("destination_cluster")
        if src_cluster in (None, "", "unknown"):
            src_cluster = None
        if dst_cluster in (None, "", "unknown"):
            dst_cluster = None
        code = attrs.get("response_code")
        is_l7 = code is not None
        grpc = attrs.get("grpc_response_status")
        # gRPC reports failures as HTTP 200 plus a status: 7 = PERMISSION_DENIED (RBAC), other non-zero = error.
        # A waypoint local reply (no upstream, no error flag, 200 or 403) is how an RBAC deny looks in metrics.
        local_reply = unreached and attrs.get("reporter") == "waypoint" and attrs.get("response_flags") == "-"
        # ztunnel marks an L4 connection refused by policy (STRICT mTLS, L4 AuthorizationPolicy) with flag DENY.
        is_denied = code == "403" or grpc == "7" or local_reply or attrs.get("response_flags") == "DENY"
        is_error = (isinstance(code, str) and code.startswith("5")) or (grpc not in (None, "", "0", "7"))

        key = (source, target)
        agg = pairs.get(key)
        if agg is None:
            pairs[key] = {"source": source, "target": target, "count": count, "mtls": is_mtls,
                          "errors": count if is_error else 0,
                          "denied": count if is_denied else 0, "l7": is_l7,
                          "source_cluster": src_cluster, "target_cluster": dst_cluster}
        else:
            agg["count"] = max(agg["count"], count)
            agg["mtls"] = agg["mtls"] and is_mtls
            if is_error:
                agg["errors"] += count
            if is_denied:
                agg["denied"] += count
            agg["l7"] = agg["l7"] or is_l7
            if agg.get("source_cluster") is None and src_cluster is not None:
                agg["source_cluster"] = src_cluster
            if agg.get("target_cluster") is None and dst_cluster is not None:
                agg["target_cluster"] = dst_cluster

    for e in pairs.values():
        sc = e.get("source_cluster")
        tc = e.get("target_cluster")
        e["cross_cluster"] = bool(sc is not None and tc is not None and sc != tc)
        for ck in ("source_cluster", "target_cluster"):
            if e.get(ck) is None:
                e.pop(ck, None)

    return list(pairs.values())


def posture(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize mesh posture (mTLS coverage, plaintext edges, denied edges) from a merged service graph."""
    edges = graph.get("edges", []) or []
    total_edges = len(edges)
    mtls_edges = sum(1 for e in edges if e.get("mtls") is True)
    plaintext_edges = sum(1 for e in edges if e.get("mtls") is False)
    unknown_edges = sum(1 for e in edges if e.get("mtls") is None)
    known = mtls_edges + plaintext_edges
    mtls_pct = round((mtls_edges / known) * 100, 1) if known else 0.0
    plaintext = [
        {"source": e["source"], "target": e["target"], "value": e.get("value", 0)}
        for e in edges if e.get("mtls") is False
    ]
    denied = [
        {"source": e["source"], "target": e["target"], "count": e.get("denied_count", 0)}
        for e in edges if e.get("denied_count", 0) > 0
    ]
    l7_edges = sum(1 for e in edges if e.get("l7") is True)
    l7_pct = round(100 * l7_edges / total_edges, 1) if total_edges else 0.0
    l4_only = [
        {"source": e["source"], "target": e["target"], "value": e.get("value", 0)}
        for e in edges if e.get("l7") is not True
    ]
    l4_only.sort(key=lambda e: e["value"], reverse=True)
    l4_only = l4_only[:50]
    clusters = set()
    for e in edges:
        for ck in ("source_cluster", "target_cluster"):
            v = e.get(ck)
            if v and v != "unknown":
                clusters.add(v)
    cross_cluster_edges = sum(1 for e in edges if e.get("cross_cluster") is True)
    cross_cluster = [
        {"source": e["source"], "target": e["target"],
         "source_cluster": e.get("source_cluster"), "target_cluster": e.get("target_cluster"),
         "value": e.get("value", 0)}
        for e in edges if e.get("cross_cluster") is True
    ]
    cross_cluster.sort(key=lambda e: e["value"], reverse=True)
    cross_cluster = cross_cluster[:50]
    return {
        "total_edges": total_edges,
        "mtls_edges": mtls_edges,
        "plaintext_edges": plaintext_edges,
        "unknown_edges": unknown_edges,
        "mtls_pct": mtls_pct,
        "plaintext": plaintext,
        "denied": denied,
        "l7_edges": l7_edges,
        "l7_pct": l7_pct,
        "l4_only": l4_only,
        "clusters": sorted(clusters),
        "cross_cluster_edges": cross_cluster_edges,
        "cross_cluster": cross_cluster,
    }


def graph_node_list(nodes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn a `{name: {type, metrics}}` map into the node dicts of a service graph."""
    return [{"id": name, "label": name, "type": data.get("type", "service"), "metrics": data.get("metrics", {})}
            for name, data in nodes.items()]


def metric_only_edge(source: str, target: str, edge: Dict[str, Any]) -> Dict[str, Any]:
    """Graph edge for a pair seen only in mesh metrics (no trace): no latency, no request rate."""
    out = {"source": source, "target": target, "value": edge["count"], "p95": 0, "req_rate": 0,
           "error_count": edge["errors"], "denied_count": edge.get("denied", 0),
           "source_kind": "metrics", "mtls": edge["mtls"], "l7": bool(edge.get("l7", False))}
    for ck in ("source_cluster", "target_cluster", "cross_cluster"):
        if ck in edge:
            out[ck] = edge[ck]
    return out


def trace_edge(source: str, target: str, data: Dict[str, Any], metric_edge: Dict[str, Any] | None) -> Dict[str, Any]:
    """Graph edge from trace data (`count`, `durations` in ms, `spans` as (start_ns, end_ns, is_error)),
    enriched with mTLS and denied state when the same pair also appears in mesh metrics."""
    durations = sorted(data["durations"])
    p95 = durations[min(int(len(durations) * 0.95), len(durations) - 1)] if durations else 0
    spans = data["spans"]
    req_rate = 0
    if spans:
        window = max((max(s[1] for s in spans) - min(s[0] for s in spans)) / 1_000_000_000, 1.0)
        req_rate = round(data["count"] / window, 2)
    out = {"source": source, "target": target, "value": data["count"], "p95": round(p95, 2), "req_rate": req_rate,
           "error_count": sum(1 for s in spans if s[2]),
           "denied_count": metric_edge.get("denied", 0) if metric_edge else 0,
           "source_kind": "traces+metrics" if metric_edge else "traces",
           "mtls": metric_edge["mtls"] if metric_edge else None, "l7": True}
    if metric_edge:
        for ck in ("source_cluster", "target_cluster", "cross_cluster"):
            if ck in metric_edge:
                out[ck] = metric_edge[ck]
    return out


def annotate_clusters(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new graph where each node gets a `cluster` from the edges that mention it.

    `source_cluster` on an edge annotates its source node, `target_cluster` its target node; the
    first known value wins. Nodes with no known cluster get no `cluster` key. Edges are unchanged.
    """
    nodes = [dict(n) for n in graph.get("nodes", [])]
    by_id = {n.get("id"): n for n in nodes}
    for e in graph.get("edges", []):
        s = by_id.get(e.get("source"))
        t = by_id.get(e.get("target"))
        sc = e.get("source_cluster")
        tc = e.get("target_cluster")
        if s is not None and sc and sc != "unknown" and "cluster" not in s:
            s["cluster"] = sc
        if t is not None and tc and tc != "unknown" and "cluster" not in t:
            t["cluster"] = tc
    return {"nodes": nodes, "edges": list(graph.get("edges", []))}
