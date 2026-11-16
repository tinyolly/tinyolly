"""changes.py: compare Istio request metrics before and after a moment in time (a change marker)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import changes  # noqa: E402


def series(dst, flag, points, code="200", src="frontend"):
    """points: [(timestamp, cumulative value)]"""
    return {"attributes": {"source_canonical_service": src, "destination_canonical_service": dst,
                           "response_flags": flag, "response_code": code},
            "datapoints": [{"timestamp": t, "value": v} for t, v in points]}


T = 1000.0   # the marker
W = 60       # window seconds


def test_delta_between_uses_cumulative_counters():
    s = series("a", "-", [(900, 10), (940, 20), (1000, 50), (1030, 80), (1060, 110)])
    assert changes.delta_between(s, T - W, T) == 30      # first point in [940, 1000] is 20, last is 50
    assert changes.delta_between(s, T, T + W) == 60
    assert changes.delta_between(s, 5000, 6000) == 0


def test_compare_around_flags_new_failures_after_the_marker():
    rows = [series("productcatalogservice", "-", [(950, 0), (1000, 100), (1060, 130)]),
            series("productcatalogservice", "UC", [(950, 0), (1000, 0), (1060, 120)]),
            series("currencyservice", "-", [(950, 0), (1000, 100), (1060, 200)])]
    out = changes.compare_around(rows, T, W)
    assert [c["service"] for c in out] == ["productcatalogservice"]      # currencyservice did not change: omitted
    c = out[0]
    assert c["before"]["requests"] == 100 and c["after"]["requests"] == 150
    assert c["before"]["failure_pct"] == 0.0 and c["after"]["failure_pct"] == 80.0
    assert c["after"]["flags"] == {"UC": 120} and c["before"]["flags"] == {}
    assert "failure" in c["summary"].lower()


def test_compare_around_reports_rate_change_without_failures():
    rows = [series("cart", "-", [(940, 0), (1000, 60), (1060, 360)])]
    out = changes.compare_around(rows, T, W)
    assert out and out[0]["service"] == "cart" and out[0]["after"]["requests"] > 3 * out[0]["before"]["requests"]
    assert "traffic" in out[0]["summary"].lower()


def test_5xx_counts_as_failure_and_empty_input_is_fine():
    rows = [series("x", "-", [(950, 0), (1000, 50), (1060, 60)], code="200"),
            series("x", "-", [(950, 0), (1000, 0), (1060, 40)], code="503")]
    c = changes.compare_around(rows, T, W)[0]
    assert c["after"]["failure_pct"] == 80.0
    assert changes.compare_around([], T, W) == [] and changes.compare_around(None, T, W) == []


def test_delta_between_treats_a_drop_as_a_counter_reset():
    s = series("a", "-", [(950, 80), (980, 110), (1000, 10), (1030, 40)])
    assert changes.delta_between(s, 900, 1100) == 30 + 10 + 30       # 80->110, reset to 10, 10->40


def edge_series(src, dst, flag, points, code="200"):
    return {"attributes": {"source_canonical_service": src, "destination_canonical_service": dst,
                           "response_flags": flag, "response_code": code},
            "datapoints": [{"timestamp": t, "value": v} for t, v in points]}


def by_edge(out):
    return {(e["source"], e["target"]): e for e in out}


def test_compare_edges_classifies_every_edge():
    rows = [
        edge_series("a", "fail", "-", [(950, 0), (1000, 100), (1060, 130)]),
        edge_series("a", "fail", "UC", [(950, 0), (1000, 0), (1060, 120)]),       # failures up
        edge_series("a", "ok", "-", [(950, 0), (1000, 100), (1060, 200)]),         # steady
        edge_series("a", "busy", "-", [(950, 0), (1000, 20), (1060, 120)]),        # traffic up 5x
        edge_series("a", "quiet", "-", [(950, 0), (1000, 100), (1060, 130)]),      # traffic down to 30%
        edge_series("a", "fresh", "-", [(950, 0), (1000, 0), (1060, 50)]),         # new
        edge_series("a", "dead", "-", [(950, 0), (1000, 80), (1060, 80)]),         # gone
        edge_series("a", "heal", "-", [(950, 0), (1000, 50), (1060, 150)]),
        edge_series("a", "heal", "UC", [(950, 0), (1000, 50), (1060, 50)]),        # failures down: 50% -> 0%
    ]
    e = by_edge(changes.compare_edges(rows, T, W))
    assert e[("a", "fail")]["change"] == "failures_up" and e[("a", "fail")]["after"]["failure_pct"] == 80.0
    assert e[("a", "ok")]["change"] == "steady"
    assert e[("a", "busy")]["change"] == "traffic_up" and e[("a", "quiet")]["change"] == "traffic_down"
    assert e[("a", "fresh")]["change"] == "new" and e[("a", "dead")]["change"] == "gone"
    assert e[("a", "heal")]["change"] == "failures_down" and e[("a", "heal")]["before"]["failure_pct"] == 50.0
    assert e[("a", "ok")]["before"]["requests"] == 100 and e[("a", "ok")]["after"]["requests"] == 100


def test_compare_edges_ignores_series_without_endpoints_and_handles_empty():
    rows = [{"attributes": {"destination_canonical_service": "x"}, "datapoints": [{"timestamp": 950, "value": 1}, {"timestamp": 1000, "value": 5}]}]
    assert changes.compare_edges(rows, T, W) == [] and changes.compare_edges(None, T, W) == []


def test_compare_edges_caps_the_after_window_at_now():
    rows = [edge_series("a", "b", "-", [(950, 0), (1000, 100), (1030, 130), (1060, 160)])]
    out = changes.compare_edges(rows, T, W, now=1030)
    assert out[0]["after"]["requests"] == 30
