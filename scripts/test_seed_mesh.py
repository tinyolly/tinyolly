"""Tests for seed_mesh.py: synthetic Istio ambient metrics (OTLP/JSON) for exercising TinyOlly's mesh features without Istio."""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("seed_mesh", pathlib.Path(__file__).with_name("seed_mesh.py"))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def series(payload, metric):
    """Yield (attrs dict, datapoint dict) for every datapoint of `metric`."""
    for rm in payload["resourceMetrics"]:
        for sm in rm["scopeMetrics"]:
            for m in sm["metrics"]:
                if m["name"] != metric:
                    continue
                body = m.get("sum") or m.get("histogram")
                for dp in body["dataPoints"]:
                    yield {a["key"]: a["value"]["stringValue"] for a in dp["attributes"]}, dp


def val(dp):
    return int(dp["asInt"])


def test_baseline_has_boutique_edges_all_mtls():
    p = seed.build_metrics_payload(1, "baseline", 1_000_000_000)
    pairs = {(a["source_canonical_service"], a["destination_canonical_service"]) for a, _ in series(p, "istio_requests_total")}
    assert ("frontend", "productcatalogservice") in pairs and ("checkoutservice", "paymentservice") in pairs
    assert ("cartservice", "redis-cart") in pairs
    assert all(a["connection_security_policy"] == "mutual_tls" for a, _ in series(p, "istio_requests_total"))
    assert all(a["response_flags"] == "-" for a, _ in series(p, "istio_requests_total"))


def test_counters_are_cumulative_and_increase():
    a = {(tuple(sorted(k.items()))): val(dp) for k, dp in series(seed.build_metrics_payload(1, "baseline", 1), "istio_requests_total")}
    b = {(tuple(sorted(k.items()))): val(dp) for k, dp in series(seed.build_metrics_payload(2, "baseline", 2), "istio_requests_total")}
    assert a.keys() == b.keys() and all(b[k] > a[k] > 0 for k in a)


def test_metric_types_and_names():
    p = seed.build_metrics_payload(1, "baseline", 1)
    names = {m["name"] for rm in p["resourceMetrics"] for sm in rm["scopeMetrics"] for m in sm["metrics"]}
    assert {"istio_requests_total", "istio_request_duration_milliseconds", "istio_tcp_connections_opened_total"} <= names
    for rm in p["resourceMetrics"]:
        for sm in rm["scopeMetrics"]:
            for m in sm["metrics"]:
                body = m.get("sum") or m.get("histogram")
                assert body["aggregationTemporality"] == 2


def test_flaky_marks_half_of_productcatalog_calls_UC():
    p = seed.build_metrics_payload(5, "flaky", 1)
    uc = sum(val(dp) for a, dp in series(p, "istio_requests_total") if a["destination_canonical_service"] == "productcatalogservice" and a["response_flags"] == "UC")
    ok = sum(val(dp) for a, dp in series(p, "istio_requests_total") if a["destination_canonical_service"] == "productcatalogservice" and a["response_flags"] == "-")
    assert uc > 0 and ok > 0 and 0.3 < uc / (uc + ok) < 0.7


def test_fault_marks_DI_on_currencyservice_and_slows_it():
    p = seed.build_metrics_payload(5, "fault", 1)
    assert any(a["response_flags"] == "DI" and a["destination_canonical_service"] == "currencyservice" for a, _ in series(p, "istio_requests_total"))
    slow = [dp for a, dp in series(p, "istio_request_duration_milliseconds") if a["destination_canonical_service"] == "currencyservice"]
    assert max(dp["sum"] / int(dp["count"]) for dp in slow) > 500


def test_canary_splits_versions_with_slow_v2():
    p = seed.build_metrics_payload(5, "canary", 1)
    by = {}
    for a, dp in series(p, "istio_request_duration_milliseconds"):
        if a["destination_canonical_service"] == "productcatalogservice" and a.get("destination_version") in ("v1", "v2"):
            c, s = by.get(a["destination_version"], (0, 0))
            by[a["destination_version"]] = (c + int(dp["count"]), s + dp["sum"])
    assert set(by) == {"v1", "v2"}
    assert by["v1"][0] > 5 * by["v2"][0] > 0
    assert by["v2"][1] / by["v2"][0] > 300 and by["v1"][1] / by["v1"][0] < 50


def test_deny_adds_plaintext_outsider_and_denied_connections():
    p = seed.build_metrics_payload(5, "deny", 1)
    out = [a for a, _ in series(p, "istio_tcp_connections_opened_total") if a["source_canonical_service"] == "outsider"]
    assert out and all(a["connection_security_policy"] == "none" for a in out)
    assert any(a["response_flags"] == "DENY" and a["source_canonical_service"] == "outsider"
               for a, dp in series(p, "istio_tcp_connections_failed_total") if val(dp) > 0)


def test_unknown_scenario_raises():
    try:
        seed.build_metrics_payload(1, "nope", 1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_event_payload_names_the_scenario():
    e = seed.event_payload("flaky")
    assert e["title"] == "scenario: flaky" and e["kind"] == "scenario" and e["attributes"] == {"scenario": "flaky"}


def test_series_carry_spiffe_principals_only_for_mtls():
    p = seed.build_metrics_payload(2, "deny", 1)
    for a, _ in series(p, "istio_tcp_connections_opened_total"):
        assert (a["source_principal"] == f"spiffe://cluster.local/ns/boutique/sa/{a['source_canonical_service']}") == (a["connection_security_policy"] == "mutual_tls")


def test_l7_option_limits_request_metrics_to_one_destination():
    p = seed.build_metrics_payload(2, "baseline", 1, l7="currencyservice")
    dests = {a["destination_canonical_service"] for a, _ in series(p, "istio_requests_total")}
    assert dests == {"currencyservice"}
    assert len({(a["source_canonical_service"], a["destination_canonical_service"]) for a, _ in series(p, "istio_tcp_connections_opened_total")}) == len(seed.EDGES)


def test_tcp_series_have_no_request_level_labels():
    p = seed.build_metrics_payload(2, "deny", 1)
    for metric in ("istio_tcp_connections_opened_total", "istio_tcp_connections_failed_total"):
        for a, _ in series(p, metric):
            assert "response_code" not in a and "request_protocol" not in a


def test_multicluster_labels_clusters_and_crosses_them():
    p = seed.build_metrics_payload(2, "multicluster", 1)
    rows = [a for a, _ in series(p, "istio_requests_total")]
    assert {a["source_cluster"] for a in rows} | {a["destination_cluster"] for a in rows} == {"cluster-a", "cluster-b"}
    assert any(a["source_cluster"] != a["destination_cluster"] for a in rows)
    assert all("source_cluster" not in a for a, _ in series(seed.build_metrics_payload(2, "baseline", 1), "istio_requests_total"))


def test_trace_payload_is_a_nested_chain_across_four_services():
    p = seed.build_trace_payload("ab" * 16, 1_000_000_000)
    spans = [(r["resource"]["attributes"][0]["value"]["stringValue"], r["scopeSpans"][0]["spans"][0]) for r in p["resourceSpans"]]
    assert [s for s, _ in spans] == ["shop-ingress-istio", "frontend", "waypoint.boutique", "productcatalogservice"]
    assert "parentSpanId" not in spans[0][1] and spans[1][1]["parentSpanId"] == spans[0][1]["spanId"]
    for (_, outer), (_, inner) in zip(spans, spans[1:], strict=False):
        assert int(outer["startTimeUnixNano"]) <= int(inner["startTimeUnixNano"]) and int(inner["endTimeUnixNano"]) <= int(outer["endTimeUnixNano"])
