"""Response-flag decoding (Envoy and ztunnel) used by get_edge."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flags  # noqa: E402


def point(flag, first, last):
    return {"attributes": {"response_flags": flag}, "datapoints": [{"timestamp": 1.0, "value": first}, {"timestamp": 2.0, "value": last}]}


def test_decode_known_flags_have_meaning_and_hint():
    for f in ("UC", "UT", "UF", "UH", "URX", "DI", "FI", "NR", "RL", "DENY", "LR", "UR", "DC"):
        d = flags.decode_flags(f)
        assert len(d) == 1 and d[0]["flag"] == f and d[0]["meaning"] and d[0]["hint"], f


def test_decode_none_and_dash_are_empty():
    assert flags.decode_flags("-") == [] and flags.decode_flags("") == [] and flags.decode_flags(None) == []


def test_decode_comma_separated_and_unknown():
    d = flags.decode_flags("UF,URX,ZZ")
    assert [x["flag"] for x in d] == ["UF", "URX", "ZZ"]
    assert "unknown" in d[2]["meaning"].lower()


def test_summarize_counts_deltas_and_shares():
    s = flags.summarize_flags([point("-", 100, 160), point("UC", 5, 45), point("DI", 0, 0)])
    assert s["total"] == 100
    assert [f["flag"] for f in s["flags"]] == ["UC"]
    assert s["flags"][0]["count"] == 40 and s["flags"][0]["share_pct"] == 40.0
    assert s["flags"][0]["meaning"] and s["flags"][0]["hint"]


def test_summarize_orders_by_count_and_merges_series_with_same_flag():
    s = flags.summarize_flags([point("UT", 0, 5), point("UC", 0, 10), point("UT", 0, 20), point("-", 0, 65)])
    assert [(f["flag"], f["count"]) for f in s["flags"]] == [("UT", 25), ("UC", 10)]
    assert s["total"] == 100


def test_summarize_empty():
    assert flags.summarize_flags([]) == {"total": 0, "flags": []}
    assert flags.summarize_flags(None) == {"total": 0, "flags": []}
