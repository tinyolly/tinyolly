---
title: "MCP server"
description: "Read-only MCP server so AI agents can query TinyOlly telemetry and read these docs: install, tools, large-trace handling"
---

# MCP server (AI agents)

`docker/apps/tinyolly-mcp` is a small, **read-only** [MCP](https://modelcontextprotocol.io) server. It lets Claude Code, Zed or any MCP client query the telemetry in your running TinyOlly (traces, spans, logs, metrics, the service catalog and the service map) and read these docs, so an agent can also answer "how do I set up / configure / use TinyOlly?". It is telemetry only: no collector config or admin operations.

## Install

1. Start TinyOlly (UI on `http://localhost:5005`).
2. Run the installer. It creates a venv and prints the exact lines to copy for your client, with your paths filled in:

    ```bash
    docker/apps/tinyolly-mcp/install.sh
    ```

3. Connect your client:

| Client | What to do |
|---|---|
| **Claude Code** | Paste the `claude mcp add tinyolly -- ...` line the installer printed. |
| **Claude Desktop** | Open `~/Library/Application Support/Claude/claude_desktop_config.json` (Settings, Developer, Edit Config opens it if your version has that menu). Paste the `"tinyolly": {...}` entry under `"mcpServers"`, then quit (Cmd+Q) and reopen Claude. |
| **Zed** | Paste the `context_servers` entry into `~/.config/zed/settings.json`. |

The client starts the server itself, so there is nothing else to run. Ask it "pretty print the service catalog" to check it works.

!!! note "Why not just a URL?"
    Claude Desktop's URL connectors are called from Anthropic's cloud, which cannot reach `localhost`. A local server is started by the client instead.

**Optional:** to use a URL (Claude Code only), run `python server.py --http --port 8765` and register it with `claude mcp add --transport http tinyolly http://127.0.0.1:8765/mcp`. To point at a TinyOlly on another address, set `TINYOLLY_URL` (default `http://localhost:5005`).

## Tools

| Tool | What it does |
|---|---|
| `list_services` | Service catalog with rate, error rate, p50/p95/p99, worst errors first (`format="table"` for a pretty table) |
| `get_service_map` | Compact caller → callee edges |
| `search_traces` | Recent traces filtered by service, errors, min duration, root name (`format="table"`) |
| `get_trace` | **Bounded summary** of a trace: duration, counts, per-service breakdown, error spans, slowest spans, depth. `format="waterfall"` draws a text waterfall |
| `get_trace_spans` | Page through a trace's spans (offset/limit, service/error/duration filters) |
| `get_span` | Full detail of one span (attributes, events, links, resource) |
| `search_spans` | Recent spans across traces filtered by service, errors, duration, name (`format="table"`) |
| `query_logs` | Logs by trace, service, severity, substring (`format="table"`) |
| `list_metrics` | Metric names with a search filter |
| `query_metric` | Time series for the last N minutes, downsampled with min/max/avg/last |
| `chart_metric` | **Image**: line chart of a metric (histograms: mean solid, p95 dashed), series labelled by what differs between them |
| `chart_service_map` | **Image**: with no arguments, the whole service map (layers of callers to callees, unconnected services in a strip below); with `service`, one service's dependencies, callers left and callees right, colored by health, edges labelled with p95 and request rate (`depth=2` for two hops) |
| `list_skills` | Investigation skills (playbooks): when to use each |
| `get_skill` | The full steps of one skill |
| `list_docs` | These documentation pages: name, title, description, section headings |
| `search_docs` | Search the docs; returns matching sections with snippets |
| `read_doc` | Read a page or just one section (paged if long) |

The same pages are also exposed as MCP resources: `tinyolly-docs://<name>` (for example `tinyolly-docs://quickstart`).

## Pretty output and visuals

The JSON tools are compact for agents. When you want something to show a person, pass `format="table"` (catalog, traces, spans, logs: markdown tables with health and severity icons, readable durations and times) or `format="waterfall"` on `get_trace` (indented span tree with timing bars; big traces keep every error span plus the slowest spans, up to `max_rows`). `chart_metric` and `chart_service_map` return PNG images, so the client must display image results (Claude Desktop and Claude Code do). Charts are drawn with matplotlib, which `install.sh` installs into the server's venv.

Claude Desktop shows tool images as a small preview. Click it to enlarge, or ask for a full-size file: both chart tools take `save_to` (for example "show me the service map and save it to ~/Desktop/map.png").

Try asking: "chart http.server.duration for tinyolly-ui", "show me the service map", "draw the service map around cart", "show the slowest checkout trace as a waterfall", "pretty print the service catalog".

## Investigation skills

Six short skills teach an agent how to investigate with these tools. They live only inside the MCP server (`docker/apps/tinyolly-mcp/skills/`); nothing is installed into Claude Code or any other client.

| Skill | Use it for |
|---|---|
| `tinyolly-triage` | "What is wrong right now?": rank services, find a failing trace, report where/what/evidence/next |
| `tinyolly-trace-investigation` | One trace: summary, waterfall, paging huge traces, self-time vs first-error reasoning |
| `tinyolly-service-deep-dive` | One service: vitals, dependency map, errors, slow traces, logs, metrics |
| `tinyolly-metrics-explorer` | Finding, charting and interpreting metrics (counters, gauges, histograms, cardinality) |
| `tinyolly-troubleshoot-stack` | TinyOlly itself is empty or unreachable (Colima contexts, ports, retention) and setup questions |
| `tinyolly-demo-failure-injection` | Break the OTel demo with a feature flag and watch TinyOlly catch it |

The server offers them three ways, so any MCP client can use them:

- **Tools:** `list_skills` and `get_skill(name)`. The server's instructions tell agents to call `list_skills` before an investigation.
- **Prompts:** one prompt per skill with an optional `focus` argument (shows up as a slash command or prompt picker where the client supports it), e.g. `tinyolly-triage` with focus "checkout is slow".
- **Resources:** `tinyolly-skills://<name>`.

The tests check that every tool and parameter a skill mentions really exists, so a skill cannot silently drift from the tools. Add one by creating `skills/<name>.md` with `name` (same as the file name) and a `description` that starts with "Use when".

## Docs

The server reads `docs/*.md` from the repo (override the location with `TINYOLLY_DOCS_DIR`). Pages are cleaned for agents: screenshots and HTML layout removed, mkdocs admonitions and tabs flattened to plain markdown, and each page is split by heading so `read_doc(name, section)` returns only what is needed. Every page starts with `title` and `description` front matter, which is what `list_docs` shows, so keep that when adding a page.

Try asking: "how do I run the OpenTelemetry demo?", "which collector presets exist and what do they do?", "what ports does TinyOlly use?".

## Large traces

Nothing returns an unbounded payload. Drill down instead of dumping: `search_traces` → `get_trace` (summary, a few KB even for a 6,000-span trace) → `get_trace_spans` (pages of up to 200 compact rows) → `get_span` for one span. Attribute values and log bodies are truncated, series are downsampled, and every response is hard-capped at `TINYOLLY_MCP_MAX_CHARS` (default 20,000) with a `truncated` flag telling the agent to narrow the query.

Try asking: "which services have the highest error rate?", "find the slowest checkout trace and tell me where the time went", "show error logs for the cart service".
