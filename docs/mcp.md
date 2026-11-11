# MCP server (AI agents)

`docker/apps/tinyolly-mcp` is a small, **read-only** [MCP](https://modelcontextprotocol.io) server. It lets Claude Code, Zed or any MCP client query the telemetry in your running TinyOlly: traces, spans, logs, metrics, the service catalog and the service map. It is telemetry only: no collector config or admin operations.

## Install

```bash
docker/apps/tinyolly-mcp/install.sh     # creates .venv and prints the registration command
```

```bash
claude mcp add tinyolly -- /path/to/tinyolly/docker/apps/tinyolly-mcp/.venv/bin/python /path/to/tinyolly/docker/apps/tinyolly-mcp/server.py
```

TinyOlly must be running (`http://localhost:5005`; override with `TINYOLLY_URL`). For HTTP instead of stdio: `python server.py --http --port 8765`.

## Tools

| Tool | What it does |
|---|---|
| `list_services` | Service catalog with rate, error rate, p50/p95/p99, worst errors first |
| `get_service_map` | Compact caller → callee edges |
| `search_traces` | Recent traces filtered by service, errors, min duration, root name |
| `get_trace` | **Bounded summary** of a trace: duration, counts, per-service breakdown, error spans, slowest spans, depth |
| `get_trace_spans` | Page through a trace's spans (offset/limit, service/error/duration filters) |
| `get_span` | Full detail of one span (attributes, events, links, resource) |
| `query_logs` | Logs by trace, service, severity, substring |
| `list_metrics` | Metric names with a search filter |
| `query_metric` | Time series for the last N minutes, downsampled with min/max/avg/last |

## Large traces

Nothing returns an unbounded payload. Drill down instead of dumping: `search_traces` → `get_trace` (summary, a few KB even for a 6,000-span trace) → `get_trace_spans` (pages of up to 200 compact rows) → `get_span` for one span. Attribute values and log bodies are truncated, series are downsampled, and every response is hard-capped at `TINYOLLY_MCP_MAX_CHARS` (default 20,000) with a `truncated` flag telling the agent to narrow the query.

Try asking: "which services have the highest error rate?", "find the slowest checkout trace and tell me where the time went", "show error logs for the cart service".
