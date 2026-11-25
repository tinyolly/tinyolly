import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sre import grade

PAY = {"id": "payment-degraded", "title": "Payment degraded", "flags": {"paymentFailure": "50%"}, "started": 1000, "ended": 1300, "announced": True,
       "expected": {"service": "payment", "cause_keywords": ["payment", "charge"], "detector": "errors"}}
QUIET = {"id": "quiet", "title": "Quiet", "flags": {}, "started": 2000, "ended": 2200, "expected": {}}
LAT = {"id": "slow-images", "title": "Slow images", "flags": {"imageSlowLoad": "5sec"}, "started": 3000, "ended": 3300,
       "expected": {"service": "image-provider", "cause_keywords": ["image", "slow"], "detector": "latency"}}


def rec(i, t, service="", cause="", status="ok", symptoms=("checkout: error rate 10%",)):
    return {"id": i, "opened_at": t, "service": service, "root_cause": cause, "summary": cause, "status": status,
            "symptoms": list(symptoms), "evidence": [{"kind": "trace", "value": "a" * 32}], "ttr_s": 200, "tool_calls": 2, "tokens_in": 10, "tokens_out": 5}


def test_results():
    hist = [PAY, QUIET, LAT]
    assert grade.grade_one(rec(1, 1090, "payment", "Payment Charge rejects calls"), hist)["result"] == "correct"
    g = grade.grade_one(rec(2, 1090, "checkout", "payment errors upstream"), hist)
    assert g["result"] == "correct" and g["ttd_s"] == 90 and g["detector_matched"]       # service named in the text counts
    assert grade.grade_one(rec(3, 1090, "load-generator", "synthetic probes, not an outage"), hist)["result"] == "wrong"
    assert grade.grade_one(rec(4, 1090, "frontend", "charge failures"), hist)["result"] == "partial"
    assert grade.grade_one(rec(5, 2100, "cart", "cart down"), hist)["result"] == "false-positive"
    assert grade.grade_one(rec(6, 1400, "payment", "payment"), hist)["result"] == "correct"           # late, within LATE_S
    assert grade.grade_one(rec(7, 1500, "payment", "payment"), hist)["result"] == "false-positive"    # too late
    assert grade.grade_one(rec(8, 3100, "image-provider", "", status="skipped"), hist)["result"] == "no-answer"
    assert grade.grade_one(rec(9, 3100, "imageprovider", "images slow"), hist)["result"] == "correct"  # name normalised


def test_missed_and_report():
    hist = [PAY, QUIET, LAT]
    out = grade.grade_all([rec(1, 1090, "payment", "payment charge")], hist)
    assert out["missed"] == ["slow-images"] and out["counts"] == {"correct": 1, "missed": 1}
    md = grade.report([rec(1, 1090, "payment", "payment charge")], hist, "m")
    assert "| 1 | Payment degraded | correct | payment | 90s |" in md and "Missed faults (no incident opened): slow-images" in md


def test_whole_word_matching():
    AD = {"id": "ad-failure", "title": "Ad", "flags": {"adFailure": "on"}, "started": 0, "ended": 300,
          "expected": {"service": "ad", "cause_keywords": ["ad", "fail"], "detector": "errors"}}
    assert grade.grade_one(rec(1, 60, "frontend", "AdService/GetAds calls fail"), [AD])["result"] == "correct"
    assert grade.grade_one(rec(2, 60, "frontend", "load spike, already degraded"), [AD])["result"] == "wrong"
    assert grade.grade_one(rec(3, 60, "checkout", "product-catalog lock contention"), [{**AD, "expected": {"service": "product-catalog", "cause_keywords": ["lock"]}}])["result"] == "correct"


def test_shadow_paging_counts():
    r1 = {**rec(1, 1090, "payment", "payment charge"), "would_page": True}
    r2 = {**rec(2, 2100, "cart", "cart down"), "would_page": True}                 # quiet period: a false page
    out = grade.grade_all([r1, r2], [PAY, QUIET, LAT])
    assert out["pages"] == {"right": 1, "missed": 1, "false": 1}
    assert "1 faults would have paged, 1 would not, 1 false pages" in grade.report([r1, r2], [PAY, QUIET, LAT])
