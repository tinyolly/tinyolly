#!/usr/bin/env python3
"""Check stored traces for structural/timing problems that would make a waterfall wrong.

Reads TinyOlly's API only (no UI). Invariants checked per trace:
  * span ids unique; span_count in the summary == spans returned
  * exactly one root; every other span's parent exists in the trace (orphans = missing data / sampling / lost spans)
  * end >= start for every span
  * child lies inside its parent's [start, end] window (tolerance --tolerance-ms); async/queue children may legitimately violate
  * summary duration == max(end) - min(start); summary start == min(start)
Usage: scripts/check-trace-integrity.py [--url http://localhost:5005] [--limit 300] [--tolerance-ms 1] [--show 5]
Exit code 1 if any hard invariant (duplicates, negative duration, summary mismatch) fails.
"""
import argparse, collections, json, sys, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:5005")
ap.add_argument("--limit", type=int, default=300)
ap.add_argument("--tolerance-ms", type=float, default=1.0)
ap.add_argument("--show", type=int, default=5, help="examples to print per issue type")
a = ap.parse_args()
get = lambda p: json.load(urllib.request.urlopen(a.url + p, timeout=30))

tol = int(a.tolerance_ms * 1e6)
issues = collections.defaultdict(list)
hard = {"duplicate_span_id", "negative_duration", "span_count_mismatch", "summary_duration_mismatch", "summary_start_mismatch"}
n_spans = 0
summaries = get(f"/api/traces?limit={a.limit}")
for t in summaries:
    tid = t["trace_id"]
    spans = get(f"/api/traces/{tid}")["spans"]
    n_spans += len(spans)
    ids = collections.Counter(s["spanId"] for s in spans)
    for sid, c in ids.items():
        if c > 1: issues["duplicate_span_id"].append(f"{tid[:8]} span {sid} x{c}")
    by = {s["spanId"]: s for s in spans}
    st = {s["spanId"]: int(s["startTimeUnixNano"]) for s in spans}
    en = {s["spanId"]: int(s["endTimeUnixNano"]) for s in spans}
    roots = [s for s in spans if not s.get("parentSpanId")]
    if len(roots) != 1: issues["root_count_!=1"].append(f"{tid[:8]} roots={len(roots)}")
    for s in spans:
        sid, pid = s["spanId"], s.get("parentSpanId")
        if en[sid] < st[sid]: issues["negative_duration"].append(f"{tid[:8]} {s['serviceName']}:{s['name']}")
        if pid:
            if pid not in by:
                issues["orphan_parent_missing"].append(f"{tid[:8]} {s['serviceName']}:{s['name']} parent={pid}")
            else:
                if st[sid] < st[pid] - tol or en[sid] > en[pid] + tol:
                    p = by[pid]
                    issues["child_outside_parent"].append(
                        f"{tid[:8]} {s['serviceName']}:{s['name']} [{(st[sid]-st[pid])/1e6:+.2f}ms start, {(en[sid]-en[pid])/1e6:+.2f}ms end] vs "
                        f"{p['serviceName']}:{p['name']}")
    if t["span_count"] != len(spans):
        issues["span_count_mismatch"].append(f"{tid[:8]} summary={t['span_count']} actual={len(spans)}")
    dur = (max(en.values()) - min(st.values())) / 1e6
    if abs(dur - t["duration_ms"]) > 0.01:
        issues["summary_duration_mismatch"].append(f"{tid[:8]} summary={t['duration_ms']:.3f}ms actual={dur:.3f}ms")
    if int(t["start_time"]) != min(st.values()):
        issues["summary_start_mismatch"].append(f"{tid[:8]} summary={t['start_time']} actual={min(st.values())}")

print(f"checked {len(summaries)} traces, {n_spans} spans (tolerance {a.tolerance_ms} ms)")
if not issues: print("OK: no issues")
for k, v in sorted(issues.items()):
    print(f"\n{'FAIL' if k in hard else 'WARN'} {k}: {len(v)}")
    for x in v[: a.show]: print("   ", x)
sys.exit(1 if any(k in hard for k in issues) else 0)
