---
title: "TinyOlly overview"
description: "What TinyOlly is, key features, supported platforms and screenshots"
---

<div align="center">
  <img src="images/tinyollytitle.png" alt="TinyOlly" width="500"><br>
  <b>The World's First Desktop Observability Platform</b>
</div>  

---

## Introducing TinyOlly

**Repository:** [https://github.com/tinyolly/tinyolly](https://github.com/tinyolly/tinyolly)

```bash
git clone https://github.com/tinyolly/tinyolly
```

### Why TinyOlly?

Why send telemetry to a cloud observability platform while coding? Why not have one on your desktop?

TinyOlly is a **lightweight OpenTelemetry-native observability platform** built from scratch to visualize and correlate logs, metrics, and traces. No 3rd party observability tools - just Python (FastAPI), SQLite, OpenAPI, and JavaScript.

### Key Features

*Ingest & compatibility*
- Native OTLP over gRPC and HTTP; works with any OTel Collector distro
- Runs on Colima (Docker and kind) on Apple Silicon, no Docker Desktop; pre-built images on Docker Hub
- Bounded retention: 30-minute TTL and 256 MB database cap, both configurable

*Explore your telemetry*
- Service catalog with RED metrics, and an interactive service dependency map
- Distributed trace waterfall with correlated logs and a per-trace service map
- Metrics Explorer with cardinality analysis and raw series
- Deep links and click-to-copy IDs: share a URL that opens straight to a trace or span

*Collector control*
- Collector presets applied from the UI via OpAMP: tail sampling, PII redaction, OTTL transforms, enrichment, metrics shaping, log dedup, derived-metric and routing connectors ([docs](collector-presets.md))

*AI & automation*
- MCP server: Claude Code, Zed or any MCP client can query traces, logs and metrics, render charts, and follow built-in investigation skills ([docs](mcp.md))
- REST API with OpenAPI documentation

*Demos*
- Realistic demo: the upstream OpenTelemetry Demo (Astronomy Shop) with failure-injection flags ([docs](otel-demo.md))

*Built with* Python (FastAPI), SQLite and JavaScript.

!!! note "Local Development Only"
    TinyOlly is *not* designed to compete with production observability platforms! It's for local development only and is not focused on infrastructure monitoring at this time.

### Platform Support

Tested on:

- Docker via Colima (macOS Apple Silicon)
- kind on Colima (macOS Apple Silicon)
- May work on other platforms

### Quick Start

Ready to try TinyOlly? Check out the [Quick Start Guide](quickstart.md) to get running in under 5 minutes!

---

## Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center" width="33%">
        <img src="images/traces.png" width="300"><br>
        <em>Trace Waterfall with Correlated Logs</em>
      </td>
      <td align="center" width="33%">
        <img src="images/logs1.png" width="300"><br>
        <em>Real-time Logs with Filtering</em>
      </td>
      <td align="center" width="33%">
        <img src="images/metrics.png" width="300"><br>
        <em>Metrics with Chart Visualization</em>
      </td>
    </tr>
    <tr>
      <td align="center" width="33%">
        <img src="images/servicecatalog.png" width="300"><br>
        <em>Service Catalog with RED Metrics</em>
      </td>
      <td align="center" width="33%">
        <img src="images/servicemap.png" width="300"><br>
        <em>Interactive Service Dependency Map</em>
      </td>
      <td align="center" width="33%">
        <img src="images/collector.png" width="300"><br>
        <em>OTel Collector Configuration (OpAMP)</em>
      </td>
    </tr>
  </table>
</div>

---

<div align="center">
  <p>Built for the OpenTelemetry community</p>
  <p>
    <a href="https://github.com/tinyolly/tinyolly">GitHub</a> •
    <a href="https://github.com/tinyolly/tinyolly/issues">Issues</a>
  </p>
</div>

