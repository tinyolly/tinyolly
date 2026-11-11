---
name: tinyolly-service-deep-dive
description: Use when the user asks about one specific service in TinyOlly: how it is doing, who calls it, what it depends on, its errors, latency, logs and metrics ("how is cart doing", "what depends on payment").
---

# Single-service deep dive

## Steps

1. **Vitals:** `list_services()` and find the row: rate, error_rate (%), p50/p95/p99, span and trace counts. If the service is missing, call `list_services(format="table")` and offer the closest names.
2. **Neighbourhood:** `chart_service_map(service)` (add `depth=2` to see two hops). Colors: blue healthy, amber some errors, red above 5%. Say who the callers and callees are and which of them are unhealthy: a failing callee explains a failing service.
3. **Errors:** `search_traces(service=..., errors_only=true, limit=5)`, then `get_trace(trace_id, format="waterfall")` on one or two, and `get_span` on the failing span.
4. **Slowness:** `search_traces(service=..., min_duration_ms=<2x p95>, limit=5)` and inspect one waterfall for the span owning the time.
5. **Logs:** `query_logs(service=..., severity="error", format="table", limit=20)`; group repeated messages mentally and report counts.
6. **Metrics:** `list_metrics(search="<keyword>")` for the service's runtime or HTTP metrics, then `chart_metric(name, service=service, minutes=30)` for the interesting ones (request duration, memory, cpu).

## Output

Lead with a one-line verdict (healthy / degraded / failing), then: vitals line, dependencies (callers → service → callees), top error with count and example trace id, top latency contributor, and what to look at next. Show the service map and one chart if they add something.

## Gotchas

- `error_rate` is a percentage of spans, not requests.
- Metrics are labelled by `service.name` resource attributes; a service can have traces but no metrics if it exports none.
- Data older than about 30 minutes is gone; mention the time window you looked at.
