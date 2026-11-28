<div align="center">
  <img src="docs/images/tinyollytitle.png" alt="TinyOlly" width="500">

  **The World's First Desktop Observability Platform**

  OpenTelemetry logs, metrics and traces on your laptop, and an AI assistant that can investigate them.

  ![OpenTelemetry native](https://img.shields.io/badge/OpenTelemetry-native-425CC7?logo=opentelemetry&logoColor=white)
  ![MCP server](https://img.shields.io/badge/MCP-28%20tools-7c3aed)
  ![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-Colima%20%2B%20kind-555555?logo=apple&logoColor=white)
  ![License](https://img.shields.io/badge/license-BSD--3-blue)

  <a href="docs/images/full/ui-otel-service-map.png"><img src="docs/images/ui-otel-service-map.png" width="820" alt="TinyOlly service map of the OpenTelemetry Demo"></a>

  [Docs](https://tinyolly.github.io/tinyolly/) · [Quick start](#quick-start) · [Ask an AI (MCP)](#ask-an-ai-about-your-telemetry-mcp) · [Teardown](#teardown)
</div>

---

TinyOlly is an observability tool that runs on your Mac. It speaks OTLP natively; no cloud, no accounts.

- **Everything correlated:** service catalog with RED metrics, service map, trace waterfalls with their logs, metrics explorer with [cardinality protection](docs/CARDINALITY-PROTECTION.md).
- **Collector control:** apply [collector presets](docs/collector-presets.md) (tail sampling, PII redaction, enrichment) from the UI over OpAMP.
- **Local and bounded:** SQLite with a 30-minute TTL and a 256 MB cap.
- **Also:** [Istio ambient](docs/istio.md), a [REST API](docs/api.md), and an AI layer on top ([MCP](#ask-an-ai-about-your-telemetry-mcp), [AI SRE](docs/ai-sre.md)).

<table>
<tr>
<td width="50%" align="center"><a href="docs/images/full/ui-traces.png"><img src="docs/images/ui-traces.png" width="440" alt="Traces"></a><br><sub>Traces: waterfall with correlated logs</sub></td>
<td width="50%" align="center"><a href="docs/images/full/ui-service-catalog.png"><img src="docs/images/ui-service-catalog.png" width="440" alt="Service catalog"></a><br><sub>Service catalog with RED metrics</sub></td>
</tr>
</table>

More screens in the [UI tour](docs/ui-tour.md).

> **Local development only.** Not a replacement for a production observability platform.

## Quick start

> **Read the [docs](https://tinyolly.github.io/tinyolly/) first.** Go through them before you install: they walk through setup, the demo, AI SRE and scenarios step by step. The commands below are only the short version.

Apple Silicon Mac with 24 GB or more; TinyOlly runs on [kind](https://kind.sigs.k8s.io/) inside [Colima](https://github.com/abiosoft/colima), no Docker Desktop.

```bash
brew install colima docker kubectl kind helm
git clone https://github.com/tinyolly/tinyolly && cd tinyolly
```

```bash
./scripts/colima-up.sh && ./scripts/kind-up.sh
./k8s/02-deploy-tinyolly.sh             # UI on http://localhost:5005
```

### Add the OpenTelemetry Demo

The Astronomy Shop, a web shop with a load generator, sending to TinyOlly:

```bash
./k8s-otel-demo/01-deploy-otel-demo-helm.sh
kubectl port-forward svc/frontend-proxy 8080:8080     # keep running; shop on http://localhost:8080
```

The first run pulls images for a few minutes, then the service map fills in at http://localhost:5005. Next: [add AI SRE](docs/ai-sre.md) → [break something](docs/scenarios.md).

To send your own telemetry instead, point OTLP at `localhost:4317` (gRPC) or `localhost:4318` (HTTP) ([details](docs/send-telemetry.md)).

## Ask an AI about your telemetry (MCP)

A read-only [MCP](https://modelcontextprotocol.io) server with **30 tools** and investigation playbooks runs next to the UI. Connect an assistant:

```bash
claude mcp add --transport http tinyolly http://127.0.0.1:8765/mcp     # Claude Code
```

Claude Desktop and Zed work too ([connect a client](docs/mcp-deploy.md)). Ask in plain English; it answers from your data and draws charts:

> *"Something is wrong with checkout. What is failing and why?"*
> *"Show me a failing order as a waterfall."*
> *"Which flag changed before payment started failing?"*

<table>
<tr>
<td width="50%" align="center"><a href="docs/images/full/mesh-otel-failure-map.png"><img src="docs/images/mesh-otel-failure-map.png" width="440" alt="Service map drawn by the MCP server with checkout and payment outlined in red"></a><br><sub><code>chart_service_map</code>: the failing services outlined in red</sub></td>
<td width="50%" align="center"><a href="docs/images/full/mesh-otel-trace-path.png"><img src="docs/images/mesh-otel-trace-path.png" width="440" alt="One failing request's journey over the service map"></a><br><sub><code>chart_trace_path</code>: one failing order, hop by hop</sub></td>
</tr>
</table>

- **[AI SRE agent](docs/ai-sre.md):** investigates incidents as they happen, using a model on your LAN, Claude or OpenAI.
- **[Agent observability](docs/technical.md#agents-llms-and-mcp-servers):** the service map shows agents, LLMs and MCP servers, with tokens per minute, tool calls and gateway blocks.
- **Tools cover** services, traces, logs, metrics, charts, TinyOlly's docs and Istio mesh checks ([every tool and playbook](docs/mcp.md) · [try it on the OpenTelemetry Demo](docs/otel-demo-ai.md)).

<table>
<tr>
<td width="50%" align="center"><a href="docs/images/full/ui-agent-map.png"><img src="docs/images/ui-agent-map.png" width="440" alt="Service map with an agent, gateway, LLM and MCP server"></a><br><sub>Agent, gateway, LLM and MCP server on the map</sub></td>
<td width="50%" align="center"><a href="docs/images/full/mesh-agent-trace-path.png"><img src="docs/images/mesh-agent-trace-path.png" width="440" alt="One agent run through the gateway to the MCP server and LLM"></a><br><sub>One agent run, hop by hop</sub></td>
</tr>
</table>

## Teardown

```bash
scripts/status.sh                          # what is running and how to remove it
scripts/teardown.sh --level vms --prune    # demos, TinyOlly, cluster, VMs, build cache
```

A dry run until you confirm ([more](docs/development.md#tear-everything-down)).

## Learn more

[Kubernetes](docs/kubernetes.md) · [Architecture](docs/technical.md) · [Development](docs/development.md) · [Release notes](release-notes/)

## License

**BSD 3-Clause**: free for individual developers, academic use and small organizations. **Commercial use** (50+ employees, production deployments, commercial products) requires a license; see [`LICENSE`](./LICENSE) and the [licensing page](docs/licensing.md).

---

<div align="center">
  <p>Built for the OpenTelemetry community</p>
  <p>
    <a href="https://github.com/tinyolly/tinyolly">GitHub</a> •
    <a href="https://github.com/tinyolly/tinyolly/issues">Issues</a>
  </p>
</div>
