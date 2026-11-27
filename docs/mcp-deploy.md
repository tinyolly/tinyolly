---
title: "MCP Server (deployment)"
description: "Run the TinyOlly MCP server so AI agents can query your telemetry: Docker Compose, Kubernetes (kind), or standalone, and how to connect Claude Code, Claude Desktop and Zed"
---

# MCP Server

The **read-only** TinyOlly MCP server lets an AI assistant (Claude Code, Claude Desktop, Zed, any MCP client) query traces, logs, metrics and the service map, draw charts and follow investigation playbooks. It ships with every TinyOlly deployment: start TinyOlly and point your client at it. What it can do: [MCP tools and playbooks](mcp.md).

## Where it runs

| Deployment | How it runs | URL |
|---|---|---|
| **Docker Compose** | A `tinyolly-mcp` service in the core compose files (`docker/` and `misc/docker-core-only/`), started and stopped with the stack. | `http://localhost:8765/mcp` |
| **Kubernetes (kind)** | A `tinyolly-mcp` Deployment and NodePort Service (`k8s/tinyolly-mcp.yaml`, `misc/k8s-core-only/tinyolly-mcp.yaml`); the kind config maps host port 8765 to it. | `http://localhost:8765/mcp` |
| **Standalone** | You run `server.py`, or the client starts it over stdio (see below). | your choice |

Docker and Kubernetes use the same URL, so client setup is identical. All clients share one server over streamable HTTP. It reads TinyOlly through the REST API (`TINYOLLY_URL`, `http://tinyolly-ui:5002` inside the stack), bundles the docs and playbooks, and binds to `127.0.0.1` in Docker.

## Check that it is up

An `initialize` call returns JSON listing `tools` and `instructions`:

```bash
curl -s -X POST http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

Docker: `docker ps --filter name=tinyolly-mcp`. Kubernetes: `kubectl get deploy tinyolly-mcp`.

## Connect a client

**Claude Code:**

```bash
claude mcp add --transport http tinyolly http://127.0.0.1:8765/mcp
```

**Claude Desktop** cannot reach a local URL (its URL connectors run in Anthropic's cloud), so bridge it with `mcp-remote` under `"mcpServers"` in `~/Library/Application Support/Claude/claude_desktop_config.json`. Use the absolute path to `npx` (nvm: `~/.nvm/versions/node/<version>/bin/npx`) and set `PATH`, because the app does not load your shell profile. Then quit (Cmd+Q) and reopen it:

```json
"tinyolly": {
  "command": "/absolute/path/to/npx",
  "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp"],
  "env": { "PATH": "/directory/containing/node:/usr/bin:/bin" }
}
```

**Zed:** add the URL as a context server, or use the stdio command (Standalone below). Then ask: "pretty print the service catalog".

## Rebuild after changes

The server is deployed by `k8s/02-deploy-tinyolly.sh`. After changing `docker/apps/tinyolly-mcp` or `docs/`, rebuild it and restart your client:

```bash
k8s/05-rebuild+deploy-mcp.sh
```

A kind cluster created before the 8765 mapping in `scripts/kind-config.yaml` cannot gain a host port; bridge it instead (Colima docker context):

```bash
docker run -d --restart=always --network kind -p 8765:8765 alpine/socat tcp-listen:8765,fork,reuseaddr tcp:tinyolly-control-plane:30876
```

Run Docker or Kubernetes, not both. When moving from Kubernetes to Docker, remove that bridge, and restart your clients after any switch:

```bash
docker rm -f tinyolly-mcp-bridge
```

## Standalone

Without containers, the client starts the server over stdio. The installer creates a venv and prints the lines for each client ([details](mcp.md#install)):

```bash
docker/apps/tinyolly-mcp/install.sh
```

Or run the HTTP server yourself (`TINYOLLY_URL` points it at TinyOlly, default `http://localhost:5005`):

```bash
python server.py --http --port 8765
```

Prefer the container: stdio keeps a stale server running until the client restarts.

## Troubleshooting

- **Old or missing tools:** restart the client after a rebuild, and check the container runs the new image.
- **Connection refused on 8765:** the stack is down, or the kind cluster predates the port mapping (use the bridge above).
- **Port 8765 in use:** the other stack or a leftover `tinyolly-mcp-bridge` is running.
- **Mesh tools or charts missing:** the image is stale; rebuild `python-base` first, then the MCP image.
