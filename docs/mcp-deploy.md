---
title: "MCP Server (deployment)"
description: "Run the TinyOlly MCP server so AI agents can query your telemetry: Docker Compose, Kubernetes (kind), or standalone, and how to connect Claude Code, Claude Desktop and Zed"
---

# MCP Server

The TinyOlly MCP server lets an AI assistant (Claude Code, Claude Desktop, Zed, any MCP client) query your traces, logs, metrics and service map, draw charts, and follow built-in investigation playbooks. It is **read-only** and ships with every TinyOlly deployment, so there is usually nothing to install: start TinyOlly and point your client at it.

This page covers running and connecting it. For what it can do, see [MCP tools and playbooks](mcp.md).

## Where it runs

| Deployment | How it runs | URL |
|---|---|---|
| **Docker Compose** | A `tinyolly-mcp` service in the core compose files (`docker/` and `misc/docker-core-only/`). It starts and stops with the stack. | `http://localhost:8765/mcp` |
| **Kubernetes (kind)** | A `tinyolly-mcp` Deployment and NodePort Service (`k8s/tinyolly-mcp.yaml`, `misc/k8s-core-only/tinyolly-mcp.yaml`). The kind config maps host port 8765 to it. | `http://localhost:8765/mcp` |
| **Standalone** | You run `server.py` yourself, or the client starts it over stdio (see below). | your choice |

Docker and Kubernetes use the same port and URL, so client configuration is identical for both. Every client shares one server over streamable HTTP. The container reads TinyOlly through its REST API (`TINYOLLY_URL`, `http://tinyolly-ui:5002` inside the stack), bundles the TinyOlly docs and the investigation skills, and binds to `127.0.0.1` on the host in Docker.

## Check that it is up

An `initialize` call should return a JSON result that lists `tools` and `instructions`:

```bash
curl -s -X POST http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

Docker: `docker ps --filter name=tinyolly-mcp`. Kubernetes: `kubectl get deploy tinyolly-mcp`.

## Connect a client

Register the URL once per client.

**Claude Code**

```bash
claude mcp add --transport http tinyolly http://127.0.0.1:8765/mcp
```

**Claude Desktop** cannot call a local URL directly (its URL connectors are called from Anthropic's cloud, which cannot reach `localhost`), so bridge it with `mcp-remote`. Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` under `"mcpServers"`. Use the absolute path to `npx` (for nvm: `~/.nvm/versions/node/<version>/bin/npx`) and set `PATH`, because the app does not load your shell profile:

```json
"tinyolly": {
  "command": "/absolute/path/to/npx",
  "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp"],
  "env": { "PATH": "/directory/containing/node:/usr/bin:/bin" }
}
```

Quit (Cmd+Q) and reopen Claude Desktop after editing.

**Zed** can keep using the stdio command (see Standalone below), or add the HTTP URL as a context server.

Then ask: "pretty print the service catalog".

## Docker Compose

The service starts with the stack:

```bash
docker compose -f docker/docker-compose-tinyolly-core-local.yml up -d
```

After you change `docker/apps/tinyolly-mcp` or `docs/`, rebuild just this service and restart your client so it reloads the tool list:

```bash
docker compose -f docker/docker-compose-tinyolly-core-local.yml up -d --build tinyolly-mcp
```

## Kubernetes (kind)

The Deployment and Service come with `k8s/02-deploy-tinyolly.sh`. To rebuild and redeploy after changes:

```bash
k8s/05-rebuild+deploy-mcp.sh
```

**A cluster created before the 8765 mapping existed** (`scripts/kind-config.yaml`): kind cannot add a host port to a running cluster, so bridge it instead of recreating the cluster. With the Colima docker context:

```bash
docker run -d --restart=always --network kind -p 8765:8765 alpine/socat tcp-listen:8765,fork,reuseaddr tcp:tinyolly-control-plane:30876
```

## Switching between Docker and Kubernetes

Run one at a time: stop one stack before starting the other. When moving from Kubernetes to Docker on an existing cluster, also remove the helper that forwards 8765 to the cluster (colima context):

```bash
docker rm -f tinyolly-mcp-bridge
```

Clients do not reconnect on their own after a switch: restart them.

## Standalone

Without containers, the client starts the server itself over stdio. The installer creates a venv and prints the exact lines for your client, with your paths filled in:

```bash
docker/apps/tinyolly-mcp/install.sh
```

| Client | What to do |
|---|---|
| **Claude Code** | Paste the `claude mcp add tinyolly -- ...` line the installer printed. |
| **Claude Desktop** | Paste the `"tinyolly": {...}` entry under `"mcpServers"` in `claude_desktop_config.json` (Settings, Developer, Edit Config opens it), then quit and reopen Claude. |
| **Zed** | Paste the `context_servers` entry into `~/.config/zed/settings.json`. |

Or run the HTTP server yourself and register the same URL:

```bash
python server.py --http --port 8765
```

Set `TINYOLLY_URL` to point at a TinyOlly on another address (default `http://localhost:5005`).

Prefer the container over per-client stdio: stdio keeps a stale copy of the server running until the client restarts.

## Troubleshooting

- **The client shows old or missing tools:** restart the client after any rebuild. Check the container is the new image (`docker compose ... up -d --build tinyolly-mcp`, or `k8s/05-rebuild+deploy-mcp.sh`).
- **Connection refused on 8765:** the stack is not running, or you are on a kind cluster created before the port mapping (use the `socat` bridge above).
- **Port 8765 already in use:** the other stack (Docker or Kubernetes) or a leftover `tinyolly-mcp-bridge` is running; see Switching above.
- **Mesh tools or charts are missing:** the image is stale. Rebuild the shared `python-base` image first, then the MCP image.
