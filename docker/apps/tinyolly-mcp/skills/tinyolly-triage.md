---
name: tinyolly-triage
description: Use when the user asks what is wrong, what is failing or slow, or wants a health check of their local TinyOlly telemetry (any "is everything ok / what broke / where are the errors" question) and the tinyolly MCP tools are available.
---

# TinyOlly triage: "what's wrong right now?"

Goal: go from "something is off" to a named service, a concrete failing trace and the evidence, in about six tool calls. Do not dump raw data; narrow step by step.

## Steps

1. **Rank services.** `list_services(format="json")`. Sort mentally by `error_rate` (a percentage) then `p95`. Ignore `tinyolly-*` services (TinyOlly's own) unless the user asks about TinyOlly itself. If the list is empty, stop and use the `tinyolly-troubleshoot-stack` skill.
2. **Show the user the overview** with `list_services(format="table")` (health icons: 🔴 >5% errors, 🟡 some errors).
3. **Pick the worst suspect(s):** highest error rate, or a p95 far above its peers. Check `get_service_map` or `chart_service_map(service)` to see whether it is the root cause or only a victim: if its callees also fail, descend to them; if only its callers fail, it is likely the source.
4. **Find a failing example.** `search_traces(service=..., errors_only=true, limit=5)`; for slowness use `min_duration_ms` instead. Use the returned **full 32-char trace_id**.
5. **Read it.** `get_trace(trace_id, format="waterfall")` and show it. Identify the first error span or the span that owns the time.
6. **Corroborate.** `query_logs(trace_id=..., format="table")`, then `get_span(trace_id, span_id)` on the culprit for its status message and attributes (http.status_code, exception events).

## Report in this shape

- **Where:** service and operation.
- **What:** error or latency, with numbers (rate, p95, count).
- **Evidence:** trace id, the failing span, the log line.
- **Next:** one concrete suggestion (check X config, rerun after Y, open service deep dive).

## Gotchas

- Durations of about 600,000 ms (10 min) on spans like `flagd.evaluation...EventStream` are long-lived streaming RPCs, not slow requests. Do not report them as latency problems.
- Data expires after 30 minutes by default; "no traces" can mean idle traffic, not an outage.
- Some HTTP spans (e.g. `telemetry-docs`, `image-provider` in the OTel demo) arrive with start time equal to end time, so they show `0` duration. That is what the source reported; do not read it as "fast".
- Trace and log tables are for showing the user; use the JSON forms when you need to reason over many rows.
