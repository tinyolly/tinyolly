---
title: "UI Tour"
description: "What each TinyOlly view shows: traces, logs, metrics, service catalog, service map, collector config"
---

# UI Tour

Open `http://localhost:5005`.

**Traces:** each trace's span waterfall with its correlated logs; click a span for its full JSON.

<div align="center">
  <a href="../images/full/ui-traces.png"><img src="../images/ui-traces.png" alt="TinyOlly Traces View" width="700"></a>
</div>

**Logs:** linked to their trace and span, filterable by severity.

<div align="center">
  <a href="../images/full/ui-logs.png"><img src="../images/ui-logs.png" alt="Logs View" width="700"></a>
</div>

**Metrics:** every metric with charts and cardinality.

<div align="center">
  <a href="../images/full/ui-metrics.png"><img src="../images/ui-metrics.png" alt="Metrics View" width="700"></a>
</div>

**Service Catalog:** rate, errors and duration per service; click a name to jump to its map node, traces, spans, logs or metrics.

<div align="center">
  <a href="../images/full/ui-otel-catalog.png"><img src="../images/ui-otel-catalog.png" alt="Service Catalog" width="700"></a>
</div>

**Service Map:** dependencies with shape for service type and colour for health (legend above the map); click a node for latency.

<div align="center">
  <a href="../images/full/ui-otel-service-map.png"><img src="../images/ui-otel-service-map.png" alt="Service Map" width="700"></a>
</div>

**OpenTelemetry Collector + OpAMP Config:** view a connected collector's config, apply changes with validation and a diff preview, or apply a [collector preset](collector-presets.md) (sampling, PII redaction, transforms, connectors and more). The collector needs the OpAMP extension (see [OpAMP configuration](otel-collector.md#opamp-configuration-optional)).

<div align="center">
  <a href="../images/full/ui-collector.png"><img src="../images/ui-collector.png" alt="OpAMP Config" width="700"></a>
</div>
