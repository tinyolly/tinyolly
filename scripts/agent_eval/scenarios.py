"""Fault scenarios with ground truth. The same neutral question is asked for every scenario, including the healthy control."""

QUESTION = ("Something may be wrong in the shop's Istio service mesh in the last few minutes, or everything may be fine. "
            "Investigate with the tools. Tell me which service is affected, what the evidence is, and the likely cause. "
            "If nothing is wrong, say the mesh looks healthy.")

SCENARIOS = {
    "baseline": {
        "describe": "healthy control: nothing injected (an agent that cries wolf fails)",
        "truth": {"service": None,
                  "healthy_any": ["healthy", "no problem", "no issues", "no issue", "nothing is wrong", "normal", "all good", "no errors"],
                  "forbidden_any": ["UC", "UT", "DENY", "DI", "outage", "injected"], "tools_any": []},
        "seed": ["baseline"], "kind": [],
    },
    "flaky": {
        "describe": "half the calls to productcatalogservice fail (response flag UC)",
        "truth": {"service": "productcatalogservice",
                  "cause_any": ["UC", "connection termination", "upstream closed", "closed the connection", "connection failure", "refus"],
                  "tools_any": ["get_edge", "what_changed", "query_metric", "get_version_split"]},
        "seed": ["baseline", "flaky"], "kind": [["waypoint"], ["flaky"]],
    },
    "fault": {
        "describe": "an injected 2 s delay on half the calls to currencyservice (flag DI)",
        "truth": {"service": "currencyservice", "cause_any": ["DI", "delay", "injected", "fault injection", "latency"],
                  "tools_any": ["get_edge", "what_changed", "query_metric", "get_trace_mesh", "compare_windows"]},
        "seed": ["baseline", "fault"], "kind": [["waypoint"], ["fault"]],
    },
    "canary": {
        "describe": "a canary sends 10% of productcatalogservice traffic to a slow v2",
        "truth": {"service": "productcatalogservice", "cause_any": ["v2", "canary", "new version"],
                  "tools_any": ["get_version_split", "what_changed", "get_edge", "query_metric"]},
        "seed": ["baseline", "canary"], "kind": [["waypoint"], ["canary"]],
    },
    "deny": {
        "describe": "STRICT mTLS refuses a plaintext outsider",
        "truth": {"service": "outsider", "cause_any": ["DENY", "denied", "refused", "STRICT", "plaintext", "mTLS"],
                  "tools_any": ["find_denied", "get_mesh_posture", "find_plaintext", "what_changed", "get_service_map"]},
        "seed": ["baseline", "deny"], "kind": [["outsider"], ["strict"]],
    },
}
