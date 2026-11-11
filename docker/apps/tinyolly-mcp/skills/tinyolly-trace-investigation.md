---
name: tinyolly-trace-investigation
description: Use when the user wants to understand one trace or find the cause of a slow or failed request in TinyOlly (a trace id, "why was this request slow", "show me the slowest checkout", huge traces with thousands of spans).
---

# Investigating a trace

Traces can have thousands of spans. Never ask for everything: go summary, then waterfall, then pages, then one span.

## Find the trace

- Given an id: use it (full 32 hex chars). Given a description: `search_traces(service=..., name_contains=..., min_duration_ms=..., errors_only=...)`. Pick by duration or errors; say which you picked and why.

## Read it

1. `get_trace(trace_id)`: duration, span/error counts, per-service totals, error spans, the slowest spans, tree depth. This is always small, even for a 6,000-span trace.
2. `get_trace(trace_id, format="waterfall", max_rows=40)`: show it to the user. On big traces it keeps every error and the slowest spans and says how many it hid.
3. Need more? `get_trace_spans(trace_id, service=..., errors_only=true)` or page with `offset`/`limit` (follow `next_offset`).
4. One suspicious span: `get_span(trace_id, span_id)` for attributes, status message, events (exceptions), links. Long values are cut at 2,000 chars.
5. `query_logs(trace_id=..., format="table")` for correlated logs.

## Reasoning rules

- **Slow trace:** the root duration is not the culprit. Find the span with the largest *self time* (its duration minus the time covered by its children). In the waterfall, look for a long bar with no nested bars under it, or gaps between sequential children (waiting, queueing, retries). Repeated identical child spans (N+1 pattern) show as a staircase of short bars: count them with `get_trace_spans(trace_id, service=...)` and compare span names.
- **Failed trace:** the *first* error in time, deepest in the tree, is usually the origin; errors above it are propagation. Check `status_message` and `http.status_code`.
- **Cross-service:** note which service each hop belongs to; a slow span in `A` whose child in `B` is slow means look inside `B`.
- A trace with only one service and no children may just be a health check.

## Report

Root cause span (service: name, duration or error), why (self time / first error), evidence (trace id, span id, log line), and the next check.
