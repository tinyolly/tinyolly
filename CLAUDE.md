# tinyolly

Local observability stack (OTLP ingest, UI, MCP server, SRE agent) on Colima.

## Layout
- `docker/apps/`: Python apps (`tinyolly-common`, `-ui`, `-otlp-receiver`, `-mcp`, `-sre`) and the Go `opamp-server`.
- `docker/otelcol-configs/`: collector configs (source of truth; then run `scripts/sync-k8s-configs.sh`).
- `k8s/`, `k8s-otel-demo/`: Kubernetes (kind). `docs/` + `mkdocs.yml`: docs site.

## Commands
- Tests (nothing runs in CI): `./scripts/test-all.sh`; `--stack` adds e2e (~8 min), `--kind` a kind smoke test (no other kind cluster may exist).
- Lint: `ruff check docker/apps/` (ruff 0.17.4).
- Docs: `python3 -m mkdocs build --strict -d /tmp/site` (venv `~/.venv/mkdocs`).
- Docker context is `colima-tinyolly`: use `docker --context colima-tinyolly ...`; new scripts must pin it.

`./mkdocs-deploy.sh` publishes the docs site: only when asked.
