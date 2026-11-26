"""AI suffix for service-map edge labels (same contract as tinyolly-ui/static/edgeLabels.js)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def ai_edge_suffix(e):
    from edge_labels import ai_edge_suffix as f   # imported per test, so a missing module fails the tests instead of collection
    return f(e)


def test_llm_tokens_per_minute():
    # 4690 + 755 tokens over 23 calls at 0.05 calls/s -> 236.7 tok/call * 3 calls/min = 710 tok/min
    assert ai_edge_suffix({"value": 23, "req_rate": 0.05, "tokens_in": 4690, "tokens_out": 755}) == "710 tok/min"
    assert ai_edge_suffix({"value": 10, "req_rate": 1, "tokens_in": 400, "tokens_out": 100}) == "3k tok/min"
    assert ai_edge_suffix({"value": 10, "req_rate": 1, "tokens_in": 700, "tokens_out": 80}) == "4.7k tok/min"


def test_llm_total_without_rate():
    assert ai_edge_suffix({"value": 3, "req_rate": 0, "tokens_in": 5000, "tokens_out": 400}) == "5.4k tok"
    assert ai_edge_suffix({"value": 3, "tokens_in": 120, "tokens_out": 0}) == "120 tok"


def test_mcp_busiest_tool():
    assert ai_edge_suffix({"value": 69, "tools": {"fetch": 23}}) == "fetch"
    assert ai_edge_suffix({"value": 9, "tools": {"search": 2, "fetch": 5, "cart": 1}}) == "fetch +2"


def test_plain_edges():
    assert ai_edge_suffix({"value": 5, "req_rate": 1}) == ""
    assert ai_edge_suffix({"value": 5, "tokens_in": 0, "tokens_out": 0, "tools": {}}) == ""
    assert ai_edge_suffix({}) == ""


def test_blocked_calls():
    assert ai_edge_suffix({"value": 0, "blocked": {"Guardrail": 2, "Authorization": 1}}) == "3 blocked"
    assert ai_edge_suffix({"value": 69, "tools": {"fetch": 23}, "blocked": {"Authorization": 4}}) == "fetch · 4 blocked"
