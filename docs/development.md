---
title: "Development and testing"
description: "Developer notes: pinned versions, lint, local test suites, Docker contexts, service catalog action layout, revert instructions"
---

# Development and testing

- Python dependencies are locked: edit `requirements.in` in a service directory, then regenerate with:

    ```bash
    uv pip compile requirements.in --universal --python-version 3.13 -o requirements.txt
    ```

- Pinned versions (collector, supervisor, Ollama, OBI, Python, Go) are listed in `versions.env`; the Dockerfiles carry matching `ARG` defaults. Update both together.
- Architecture diagram (`docs/images/architecture.png`) is generated: edit `scripts/make-architecture-diagram.py` and run `docker/apps/tinyolly-mcp/.venv/bin/python scripts/make-architecture-diagram.py` (needs matplotlib and Pillow).
- Lint (rules are in `ruff.toml`; keep the ruff version pinned, its defaults change between releases). There is no CI; run the checks locally:

    ```bash
    pip install ruff==0.17.4
    ruff check docker/apps/
    ```

- **All local tests** (fast suites; `--stack` adds the e2e run against the running stack, `--kind` adds the kind smoke test, which briefly stops the compose stack). Nothing runs in CI. Docs pages need `title`/`description` front matter (the MCP server lists them). Suites: common, UI/API, receiver, MCP server, frontend JS (`node --test`), Go, collector configs, kubectl guard:

    ```bash
    ./scripts/test-all.sh
    ```

- Individual suites. Common library:

    ```bash
    (cd docker/apps/tinyolly-common && pip install -r requirements-test.txt . && pytest tests)
    ```

- Go (OpAMP server: gofmt, vet, `go test -race` in the pinned golang image), UI tests, and the k8s safety guard:

    ```bash
    ./scripts/test-go.sh
    (cd docker/apps/tinyolly-ui && pytest tests)
    ./scripts/test-kubectx-guard.sh
    ```

- End-to-end (needs the stack up, ~8 min; `--up` starts it, `--only a,b` picks scenarios, `--list` shows them):

    ```bash
    python3 scripts/e2e.py
    ```

    Drives OTLP through the collector, applies every preset via OpAMP, and checks results through the UI API. Test hooks: `POST /admin/reset`, `POST /api/opamp/config?wait=N`.
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

## Testing mesh features without Istio

Docker Compose has no Istio, so `scripts/seed_mesh.py` posts synthetic Istio metrics (OTLP/JSON) for the Online Boutique mesh: scenarios `baseline`, `flaky`, `fault`, `canary`, `deny` and `multicluster`, plus `--trace` (a trace through a gateway and a waypoint), `--l7 <service>` (request metrics for one destination only) and `--ui <url>` (records a change marker).

To run the Compose stack next to the kind cluster, use the second Colima VM and shifted ports (UI 5105, MCP 8865, OTLP 4418):

```bash
scripts/docker-alt.sh                      # rebuild python-base and every service, then start (docker/docker-compose.altports.yml)
python3 scripts/seed_mesh.py --otlp http://localhost:4418 --scenario flaky --ui http://localhost:5105
MCP_URL=http://localhost:8865/mcp ...      # then ask the MCP server (get_edge, what_changed, chart_map_diff)
```

## Agent eval

`scripts/agent_eval/eval.py` injects a known fault, lets a local model investigate through the MCP tools, and grades the answer against ground truth (service, cause, evidence). It has five scenarios including a healthy control, and runs against Compose (seeded metrics) or kind (real faults from the demo repo):

```bash
python3 scripts/agent_eval/eval.py --target docker --repeat 3
python3 scripts/agent_eval/eval.py --target kind --scenarios flaky,deny --no-skill-hint
```

Needs Ollama (`LOCAL_BASE`, `LOCAL_MODEL`). Results go to `eval-results.json`. Unit tests for the loop and grader:

```bash
pytest scripts/agent_eval
```

## Documentation images

Screenshots in the README and docs are generated, not hand-pasted, so they can be refreshed in one command. `scripts/make-doc-images.py` takes headless-Chrome screenshots of the UI tabs and saves the PNGs the MCP chart tools return, and writes each twice: a preview at most 900 px wide in `docs/images/` (what the docs show) and the full-size file in `docs/images/full/` (what a click opens).

```bash
scripts/make-doc-images.py                       # all shots from the running stack (UI :5005, MCP :8765)
scripts/make-doc-images.py --only mesh-map-diff  # one shot
scripts/make-doc-images.py --seed --otlp http://localhost:4318   # post a fault scenario first (diff and trace path)
scripts/make-doc-images.py --check               # no stack needed; also runs in test-all.sh
```

To add a screenshot, add a line to `SHOTS` in the script, run it, and embed it as `[![alt](images/<name>.png)](images/full/<name>.png)`, or, where a width is needed, `<a href="../images/full/<name>.png"><img src="../images/<name>.png" width="400"></a>`. The path prefix depends on the syntax: MkDocs resolves markdown links from the source file and rewrites them, so markdown under `docs/` uses `images/`; raw HTML is not rewritten and the page is served at `/<page>/`, so HTML under `docs/` uses `../images/` (except `docs/index.md`, which is the site root: `images/`). The README uses `docs/images/` for both. `--check` fails when a shot is missing, a preview is over 300 KB, or a doc embeds a generated shot without the click-to-expand link. The shots come from whatever is running: use a stack with mesh data (the seeder, or the Istio demo) for the `mesh-*` shots, and set `TINYOLLY_UI`, `TINYOLLY_MCP` for another port. It needs Chrome (`CHROME=` overrides the path) and Pillow or macOS `sips`.

## Docker contexts

Two Colima VMs can coexist: `colima` (default) and `colima-tinyolly` (this project). Every script pins `DOCKER_CONTEXT=colima-${COLIMA_PROFILE:-tinyolly}` at the top; new scripts that call `docker` must do the same (copy the 3-line block from any `0N-*.sh`). For ad hoc commands use `docker --context colima-tinyolly ...`.

## Service catalog actions (UI layout, easy revert)

In the APM Service Catalog, per-service actions (Traces, Spans, Logs, Metrics, Service map) are a popover menu opened by clicking the service name. The original layout, a row of buttons on every service, is still in the code.

To revert, set `ACTIONS_STYLE = 'buttons'` at the top of `docker/apps/tinyolly-ui/static/serviceCatalog.js` and rebuild the UI image:

```bash
cd docker
DOCKER_CONTEXT=colima-tinyolly docker compose -f docker-compose-tinyolly-core-local.yml up -d --build --no-deps tinyolly-ui
```

To remove the menu code entirely, delete `SERVICE_ACTIONS`, `openServiceMenu`, `closeServiceMenu`, the `data-service-menu` click handler and the two `document.addEventListener` lines.
Map and Service Catalog cross-links (`window.viewServiceMap`, `window.viewServiceCatalog`) are independent of this setting.
