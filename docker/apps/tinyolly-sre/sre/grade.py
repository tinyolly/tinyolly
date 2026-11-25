"""Scores the agent's investigations against the faults the demo driver injected (ground truth the agent never sees).

Per investigation: correct (named the faulty service AND the cause), partial (one of the two), wrong (neither),
false-positive (no fault was active). Per injected fault with no investigation: missed. Counts, not percentages."""
from __future__ import annotations
import re, time

LATE_S = 150          # an incident opened this long after a fault ended still belongs to it (detector windows lag)
DETECTOR_WORDS = {"errors": ("error",), "latency": ("p95", "latency", "slow"), "traffic": ("rate", "traffic", "req/s"), "platform": ("platform", "series", "storage")}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _words(s: str) -> str:
    """' ad service get ads payment ' from 'AdService/GetAds payment': camelCase split, lowercased, padded for whole-word tests."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s or "").lower())) + " "


def _has_service(text: str, svc: str) -> bool:
    w, parts = _words(text), _words(svc).strip()
    return bool(parts) and (f" {parts} " in w or f" {parts.replace(' ', '')} " in w)


def _scenario_for(rec: dict, history: list[dict]):
    t = rec.get("reinvestigated_at") or rec.get("opened_at") or 0      # a re-investigation answers the fault that triggered it
    hits = [h for h in history if h["started"] <= t <= (h["ended"] or time.time()) + LATE_S]
    return max(hits, key=lambda h: h["started"]) if hits else None


def grade_one(rec: dict, history: list[dict]) -> dict:
    h = _scenario_for(rec, history)
    if not h or h["id"] == "quiet" or not h.get("flags"):
        return {"result": "false-positive", "scenario": h["id"] if h else "", "ttd_s": None, "paged": rec.get("would_page")}
    exp = h.get("expected") or {}
    raw = " ".join(str(rec.get(k) or "") for k in ("root_cause", "summary")); text = _words(raw)
    svc = _norm(exp.get("service", ""))
    named = bool(svc) and (_norm(rec.get("service", "")) == svc or _has_service(raw, exp.get("service", "")))
    cause = any(f" {k.lower()}" in text for k in exp.get("cause_keywords", []))      # word start: "fail" matches "failing"
    symptoms = " ".join(rec.get("symptoms") or []).lower()
    detector = any(w in symptoms for w in DETECTOR_WORDS.get(exp.get("detector", ""), ()))
    result = "correct" if named and cause else "partial" if named or cause else "wrong"
    if rec.get("detection_only"):                    # replay without a model: did a detector point at the faulty service?
        where = " ".join(rec.get("symptoms") or []) + " " + " ".join(rec.get("blast_radius") or [])
        result = "detected" if svc and _has_service(where, exp.get("service", "")) else "detected-elsewhere"
    if not rec.get("detection_only") and (rec.get("status") in ("skipped", "error") or not rec.get("summary")): result = "no-answer"
    return {"result": result, "scenario": h["id"], "scenario_title": h["title"], "service_named": named, "cause_named": cause,
            "detector_matched": detector, "expected_service": exp.get("service", ""), "ttd_s": int((rec.get("reinvestigated_at") or rec["opened_at"]) - h["started"]),
            "ttr_s": rec.get("ttr_s"), "trace_cited": any(e.get("kind") == "trace" for e in rec.get("evidence") or []),
            "announced": h.get("announced", True), "paged": rec.get("would_page")}


def grade_all(records: list[dict], history: list[dict]) -> dict:
    grades = {r["id"]: grade_one(r, history) for r in records}
    claimed = {g["scenario"] for g in grades.values() if g["result"] != "false-positive"}
    missed = [h["id"] for h in history if h.get("flags") and h["id"] not in claimed and h.get("ended")]
    counts: dict[str, int] = {}
    for g in grades.values(): counts[g["result"]] = counts.get(g["result"], 0) + 1
    counts["missed"] = len(missed)
    # shadow paging: a real fault should page once (act_now); nothing else should page
    paged_faults = {gr["scenario"] for gr in grades.values() if gr["result"] != "false-positive" and gr.get("paged")}
    faults = [h["id"] for h in history if h.get("flags") and h.get("ended")]
    pages = {"right": len([f for f in faults if f in paged_faults]), "missed": len([f for f in faults if f not in paged_faults]),
             "false": sum(1 for gr in grades.values() if gr["result"] == "false-positive" and gr.get("paged"))}
    return {"grades": grades, "missed": missed, "counts": counts, "pages": pages}


def _s(v): return "-" if v is None else f"{v}s"


def report(records: list[dict], history: list[dict], model: str = "") -> str:
    g = grade_all(records, history); by = {r["id"]: r for r in records}
    rows = ["| # | Injected fault | Result | Service named | TTD | TTR | Tool calls | Tokens |", "|---|---|---|---|---|---|---|---|"]
    for i, gr in sorted(g["grades"].items()):
        r = by[i]
        rows.append(f"| {i} | {gr.get('scenario_title') or gr['scenario'] or '(none active)'} | {gr['result']} | {r.get('service') or '-'} | "
                    f"{_s(gr['ttd_s'])} | {_s(r.get('ttr_s'))} | "
                    f"{r.get('tool_calls', 0)} | {r.get('tokens_in', 0) + r.get('tokens_out', 0)} |")
    faults = [h for h in history if h.get("flags")]
    quiet = [h for h in history if not h.get("flags")]
    c = g["counts"]
    head = [f"# TinyOlly AI SRE Agent: shift report", "", f"Model: {model or '-'}. Faults injected: {len(faults)}. Quiet periods: {len(quiet)}. "
            f"Change markers {'published' if all(h.get('announced', True) for h in history) else 'withheld for some faults'}.", "",
            "Counts (small sample; not percentages): " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())), "",
            f"Paging (shadow mode, nothing was paged): {g['pages']['right']} faults would have paged, {g['pages']['missed']} would not, {g['pages']['false']} false pages.", ""]
    tail = ["", "Missed faults (no incident opened): " + (", ".join(g["missed"]) or "none")]
    return "\n".join(head + rows + tail) + "\n"
