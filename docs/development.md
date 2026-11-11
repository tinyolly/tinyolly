---
title: "Development and testing"
description: "Developer notes: pinned versions, lint, local test suites, Docker contexts, service catalog action layout, revert instructions"
---

# Development and testing

- Python dependencies are locked: edit `requirements.in` in a service directory, then regenerate with
  `uv pip compile requirements.in --universal --python-version 3.13 -o requirements.txt`.
- Pinned versions (collector, supervisor, Ollama, OBI, Python, Go) are listed in `versions.env`; the Dockerfiles carry matching `ARG` defaults. Update both together.
- Architecture diagram (`docs/images/architecture.png`) is generated: edit `scripts/make-architecture-diagram.py` and run `docker/apps/tinyolly-mcp/.venv/bin/python scripts/make-architecture-diagram.py` (needs matplotlib and Pillow).
- Lint: `pip install ruff==0.17.4 && ruff check docker/apps/` (rules are in `ruff.toml`; keep the ruff version pinned, its defaults change between releases). There is no CI; run the checks locally.
- **All local tests:** `./scripts/test-all.sh` (fast suites; `--stack` adds the e2e run against the running stack, `--kind` adds the kind smoke test, which briefly stops the compose stack). Nothing runs in CI. Docs pages need `title`/`description` front matter (the MCP server lists them). Suites: common, UI/API, receiver, MCP server, frontend JS (`node --test`), Go, collector configs, kubectl guard. Individually:
- Tests: `cd docker/apps/tinyolly-common && pip install -r requirements-test.txt . && pytest tests`.
- Go (OpAMP server): `./scripts/test-go.sh` (gofmt, vet, `go test -race` in the pinned golang image). UI tests: `cd docker/apps/tinyolly-ui && pytest tests`. k8s safety guard: `./scripts/test-kubectx-guard.sh`.
- End-to-end (needs the stack up, ~8 min): `python3 scripts/e2e.py` (`--up` starts it, `--only a,b` picks scenarios, `--list`). Drives OTLP through the collector, applies every preset via OpAMP, and checks results through the UI API. Test hooks: `POST /admin/reset`, `POST /api/opamp/config?wait=N`.
- Collector configs: `./scripts/test-collector-configs.sh` (validate + start every preset); after editing them run `./scripts/sync-k8s-configs.sh`.

## Technical details

### Stack
- **Backend**: FastAPI (async), SQLite with ZSTD compression + msgpack
- **Frontend**: Vanilla JavaScript, HTML, CSS
- **Ingestion**: OTLP/gRPC and OTLP/HTTP
- **Storage**: 30-minute TTL, sorted sets indexed by timestamp
- **Correlation**: Native trace/span/log linking

### OTLP Support
- Full OpenTelemetry Protocol compliance
- ResourceSpans, ResourceLogs, ResourceMetrics
- Spanmetrics integration for RED metrics
- OpAMP protocol support for remote collector configuration management
- No vendor lock-in

## Docker contexts

Two Colima VMs can coexist: `colima` (default) and `colima-tinyolly` (this project). Every script pins `DOCKER_CONTEXT=colima-${COLIMA_PROFILE:-tinyolly}` at the top; new scripts that call `docker` must do the same (copy the 3-line block from any `0N-*.sh`). For ad hoc commands use `docker --context colima-tinyolly ...`.

## Service catalog actions (UI layout, easy revert)

In the APM Service Catalog, per-service actions (Traces, Spans, Logs, Metrics, Service map) are a popover menu opened by clicking the service name. The original layout, a row of buttons on every service, is still in the code.

To revert, set `ACTIONS_STYLE = 'buttons'` at the top of `docker/apps/tinyolly-ui/static/serviceCatalog.js` and rebuild the UI image
(`cd docker && DOCKER_CONTEXT=colima-tinyolly docker compose -f docker-compose-tinyolly-core-local.yml up -d --build --no-deps tinyolly-ui`).
To remove the menu code entirely, delete `SERVICE_ACTIONS`, `openServiceMenu`, `closeServiceMenu`, the `data-service-menu` click handler and the two `document.addEventListener` lines.
Map and Service Catalog cross-links (`window.viewServiceMap`, `window.viewServiceCatalog`) are independent of this setting.
