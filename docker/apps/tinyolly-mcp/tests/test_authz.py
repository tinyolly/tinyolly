"""authz.py: draft a least-privilege AuthorizationPolicy from observed callers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import authz  # noqa: E402

CALLERS = [{"service": "frontend", "principal": "spiffe://cluster.local/ns/boutique/sa/frontend"},
           {"service": "checkoutservice", "principal": "spiffe://cluster.local/ns/boutique/sa/checkoutservice"},
           {"service": "frontend", "principal": "spiffe://cluster.local/ns/boutique/sa/frontend"}]


def test_build_policy_lists_unique_sorted_principals_without_spiffe_prefix():
    y = authz.build_policy("cartservice", "boutique", CALLERS)
    assert "apiVersion: security.istio.io/v1" in y and "kind: AuthorizationPolicy" in y
    assert "name: cartservice-allow-observed-callers" in y and "namespace: boutique" in y
    assert "app: cartservice" in y and "action: ALLOW" in y
    a, b = y.index("cluster.local/ns/boutique/sa/checkoutservice"), y.index("cluster.local/ns/boutique/sa/frontend")
    assert a < b and y.count("sa/frontend") == 1 and "spiffe://" not in y


def test_build_policy_with_no_identities_returns_none():
    assert authz.build_policy("x", "boutique", []) is None
    assert authz.build_policy("x", "boutique", [{"service": "a", "principal": ""}, {"service": "b"}]) is None


def test_summarize_callers_splits_mtls_and_plaintext_and_counts_growth():
    def s(src, principal, policy, first, last, ns="boutique"):
        return {"attributes": {"source_canonical_service": src, "source_principal": principal, "connection_security_policy": policy,
                               "source_workload_namespace": ns, "destination_workload_namespace": "boutique"},
                "datapoints": [{"timestamp": 1.0, "value": first}, {"timestamp": 2.0, "value": last}]}
    out = authz.summarize_callers([
        s("frontend", "spiffe://cluster.local/ns/boutique/sa/frontend", "mutual_tls", 0, 10),
        s("frontend", "spiffe://cluster.local/ns/boutique/sa/frontend", "mutual_tls", 5, 10),     # same caller, second series
        s("outsider", "", "none", 0, 4, ns="outside"),
        s("idle", "spiffe://cluster.local/ns/boutique/sa/idle", "mutual_tls", 0, 0),             # never connected: ignored
        s("steady", "spiffe://cluster.local/ns/boutique/sa/steady", "mutual_tls", 3, 3)])        # long-lived connection: flat but real
    assert out["namespace"] == "boutique"
    assert out["mtls"] == [{"service": "frontend", "principal": "spiffe://cluster.local/ns/boutique/sa/frontend", "calls": 15},
                           {"service": "steady", "principal": "spiffe://cluster.local/ns/boutique/sa/steady", "calls": 0}]
    assert out["plaintext"] == [{"service": "outsider", "namespace": "outside", "calls": 4}]
