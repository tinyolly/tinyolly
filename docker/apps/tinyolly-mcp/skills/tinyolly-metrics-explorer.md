---
name: tinyolly-metrics-explorer
description: Use when the user wants to find, chart or interpret metrics in TinyOlly ("what metrics exist for X", "graph request duration", "is memory growing", cardinality questions).
---

# Exploring metrics

## Steps

1. **Discover:** `list_metrics(search="duration")` (substring of name or description). The result includes `type` (sum, gauge, histogram) and `unit`. If nothing matches, try a broader term, then `list_metrics(limit=100)`.
2. **Look:** `chart_metric(name, service=..., minutes=15)` returns a PNG. Show it. For histograms the chart draws per-datapoint mean (solid) and p95 estimate (dashed) in the same color; series are labelled by the attributes that differ (route, status).
3. **Numbers:** `query_metric(name, service=..., minutes=...)` returns min/max/avg/last per series, downsampled. Use it to quote values or to compare services; use the chart for shape.
4. **Compare services:** call `chart_metric` per service, or `query_metric` without `service` and compare the per-series `service` fields.

## Interpreting

- **Sum (counter) metrics are cumulative:** a rising line is normal; look at the slope. A drop to zero is a restart.
- **Gauges** are point-in-time values (memory, queue depth).
- **Histograms:** compare p95 to mean; a large gap means a long tail.
- Units matter: durations may be `ms` or `s` depending on the semantic-convention version; say which.
- Too many series (`series_total` large) means high cardinality: name the label that explodes (look at the `attributes` in the series) and suggest dropping or aggregating it. Details: `read_doc("metrics")` and `read_doc("cardinality-protection")`.

## Limits

TinyOlly caps unique metric names at 1,000 by default; the metrics tab turns red at 80%. Outputs are bounded: at most 12 series per chart, 50 per query, 200 points.
