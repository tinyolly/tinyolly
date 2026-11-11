# Handoff — TinyOlly modernization (2026-11-09)

Everything needed to continue on another computer. Read this first, then `plans/2026-11-modernization-plan.md` (status table + execution log).

## Where things are

* **Branch flow:** `v3-integration` was merged into `main` on 2026-11-10 (PRs #8–#13) and deleted. All work is on `main`; there are no open PRs or side branches (besides `gh-pages`). For new work, branch from `main` and open PRs into `main`.
* The phase branches were stacked and are no longer needed (they were local-only except `modernize/phase-4-otel-demo`, which is merged). For reference, the phase boundaries were: phase 0 `bef08a0`, phase 1 `4ba7eab`, phase 2 `d90f300`, phase 3 `3327ed2`, phase 4 `cc524eb`+.
* Commit author used throughout: `Steve Lerner <stevelerner@gmail.com>` (no git identity was configured on the original machine; set your own with `git config user.name/email` before committing).
* Plans: `plans/2026-11-modernization-plan.md` (main), `plans/2026-11-trace-accuracy-plan.md` (next work), `plans/supplemental/` (OTel Demo leftovers, Android app, removing security hardening; none started).

## Current state (2026-11-10)

Everything is merged into `main`; core images are on Docker Hub. The review work (P0, P1, P2) is done, preset behaviour is covered by `scripts/e2e.py` (88 checks) and `scripts/test-preset-behavior.py`, and the service map/catalog UI was reworked (shapes = type, colors = health, name menu, cross-links). Lessons worth keeping:

* Test containers must be named `pt-*` (a script once nearly `docker rm -f`'d a real service). Use fakes or standalone-collector tests, not the live collector, for destructive probes.
* `scripts/test-collector-configs.sh` mounts a writable `/var/lib/otelcol` (the supervisor image has it, plain contrib does not).
* Debug exporter output uses `ResourceLog #n` (singular) for logs, `ResourceSpans`, `ResourceMetrics`.

## Automated end-to-end test (added 2026-11-10)

`python3 scripts/e2e.py` drives a RUNNING stack only through its APIs (stdlib only, ~8 min, 88 checks): baseline pipeline (traces/logs/metrics/exemplars/service map/catalog), the OpAMP apply flow, and every collector preset with behaviour assertions. `--up` starts Colima + the stack first, `--only a,b` / `--list` select scenarios. **After changing `tinyolly-common` rebuild the base image first** (`docker build -t tinyolly/python-base:latest -f docker/dockerfiles/Dockerfile.tinyolly-python-base docker/`): `docker compose --build` does not rebuild it, so the UI/receiver silently keep the old library (this hid fixes for a while).

Test hooks added for it: `POST /admin/reset` (delete all telemetry), `POST /api/opamp/config?wait=N` (returns per-agent applied/failed + `config_hash`), `config_status`/`applied_config_hash` in `/api/opamp/status`.

Bugs the e2e run found and fixed: `/admin/stats` 500 once any metric existed (`percent_used` float vs int model); `database is locked` drops of whole receiver batches (writes now `BEGIN IMMEDIATE` + `busy_timeout` set before WAL + retry with backoff); **exponential histograms were silently dropped** (now converted to explicit buckets at ingest).

## Set up a new machine (macOS)

```bash
brew install colima docker docker-compose docker-buildx docker-credential-helper kubectl kind helm uv
mkdir -p ~/.docker && echo '{"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}' > ~/.docker/config.json   # merge if the file exists
git clone https://github.com/tinyolly/tinyolly && cd tinyolly
./scripts/colima-up.sh                       # 4 CPU / 4 GB default; COLIMA_MEMORY=8 on bigger machines
cd docker && ./01-start-core-local.sh        # build from this checkout (Docker Hub images predate these changes)
open http://localhost:5005
cd ../docker-otel-demo && ./01-start-otel-demo.sh   # shop on :8080, flags: ./03-set-flag.sh
```

The original machine was an **8 GB / 8-core Apple Silicon Mac**; every sizing decision (Colima 4 GB, 16-service demo subset, no Kafka) comes from that. On a bigger machine you can raise `COLIMA_MEMORY`, run the demo's Kafka services (`compose.full.yaml`) and the Helm chart.

Tests / checks you can run without a cluster:

```bash
cd docker/apps/tinyolly-common && pip install -r requirements-test.txt . && pytest tests     # 11 tests
./scripts/test-collector-configs.sh          # validate + start every collector config with the pinned image
./scripts/sync-k8s-configs.sh && git diff --exit-code k8s k8s-core-only                       # k8s ConfigMaps in sync
python3 scripts/check-trace-integrity.py     # against a running stack with data
```

## What is done

See the status table in the modernization plan. Short version: Colima + kind runtime (Phase 1), pinned/locked deps (2), eight collector presets with a test harness (3), the upstream OpenTelemetry Demo as the demo (4), plus fixes found by running it (error-status detection, PII preset leaking CVV, sticky header).

## Things that are NOT done or NOT verified (be skeptical here)

* Phase 1: `k8s-demo`, `k8s-demo-ebpf`, `k8s-core-only`, cleanup and `04-rebuild*` scripts were converted from minikube but never run on kind; the eBPF demo under Colima `vz` is unchecked; `scripts/lib/preflight.sh` is not sourced by the `01-*.sh` scripts.
* Phase 2: `docker-demo-ebpf` and `docker-ai-agent-demo` images build but were never run on the new Python 3.13 locks; GenAI semconv in the AI agent demo not reviewed; `versions.env` and the Dockerfile `ARG` defaults are duplicated by hand (no sync check).
* Phase 3: presets `enrichment`, `metrics-shaping`, `connectors-metrics` applied with zero collector errors but their output was not inspected; the transform preset's "derive severity from body" rule was never exercised; k8s ConfigMaps (generated) not deployed to kind; `k8s-core-only` embeds its own collector config in `tinyolly-opamp-server.yaml` (not synced).
* Phase 4 (demo): moved to `plans/supplemental/otel-demo-and-demo-apps.md`.
* UI visual checks: the user tested the UI visually (service map, charts after the Chart.js/Cytoscape bumps) and reported it fine; the sticky-header fix was deployed but not re-checked by eye.
* Tests: the skipped UI test stubs were removed. Lint was fixed: `ruff.toml` has an explicit rule set; use `ruff==0.17.4` (defaults change between releases). The receiver has a small hardening test file; CI does not exist.
* **CI was removed** (2026-11-09): `.github/workflows/test.yml` was deleted (it had been failing on `main` since at least March 2026) and `release.yml` no longer gates on it. All checks are local scripts. `.github/dependabot.yml` (added in Phase 2) is still there: delete it if you do not want automatic dependency PRs.

## Gotchas learned (save yourself the time)

1. **Supervisor merges, it does not replace.** Remote collector configs are merged into the base `config.yaml` by pipeline name, so a preset must define `traces`/`metrics`/`logs` itself or the base pipelines keep running (sampling was silently bypassed until fixed). Remote configs arrive on the agent's next check-in: wait for the effective config to change (10–30 s) before testing.
2. **OTel Demo image tags:** its `.env` defaults `DEMO_VERSION=latest`, which does not match the pinned git tag; `01-start-otel-demo.sh` pins it. Don't run the demo's compose file by hand without `DEMO_VERSION=3.1.0`.
3. **`tinyolly-common` is baked into `tinyolly/python-base`.** After editing it, rebuild the base image (`docker build -t tinyolly/python-base:latest -f docker/dockerfiles/Dockerfile.tinyolly-python-base docker/`) or the UI keeps the old code even after `--build`.
4. **Ports:** the docker stack and the kind cluster both bind 4317/4318/5005; run one at a time. Docker Desktop is not used anymore; `host.docker.internal` is how containers reach the host collector under Colima (used by the demo).
5. **Bash 3.2 on macOS** was the harness shell: avoid heredocs inside `$(...)`, arrays, backticks in ad-hoc commands.
6. Colima mounts `$HOME` only: files in `/tmp` are not visible to containers (bind mounts of `/tmp/x` became empty directories). Put test files inside the repo and delete them.
7. `.gitignore` lacked a trailing newline once and an `echo >>` corrupted the last pattern; check `git status` for stray `docker-otel-demo/.demo` before `git add -A`.

## Not in the repo (lost if you only have the clone)

* The generator used to produce the preset YAML (`/tmp/gen/gen.py`) — presets are plain files now; edit them directly, then run `./scripts/sync-k8s-configs.sh` and `./scripts/test-collector-configs.sh`.
* Helper scripts used for live testing (`/tmp/apply.sh`, `/tmp/apply2.sh`): they POST a template to `/api/opamp/config` and poll `/api/opamp/status` for a marker. Recreate if needed (`GET /api/opamp/templates/<id>` → `POST /api/opamp/config {"config": ...}`).
* The telemetry used for testing was `telemetrygen` (`ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:v0.165.0`) on the `tinyolly-network` docker network.
* Machine state: Colima VM, brew packages, `~/.docker/config.json`, pulled images. A uv-built venv at `/tmp/v2` was used for Python tests.

## Suggested next steps (in order)

1. For each chunk of work: branch from `main`, run the local checks above, open a PR into `main`, then review it with Claude (`/code-review <PR number> --comment` posts inline findings; there is no CI and no Copilot review in this repo).
2. Close the verification gaps above that are cheap: run `k8s-demo` / `k8s-core-only` on kind, inspect the three un-inspected presets, run the remaining demo flags.
3. **Trace accuracy / waterfall work** (`plans/2026-11-trace-accuracy-plan.md`): fixtures → BigInt timestamps → nest spans by parent → fix the 100-span cap → incomplete-trace indicator → Jaeger diff → render test.
4. Phase 5 UI gaps (exemplar→trace links, span events/exceptions pane, span links, processor-effect panel on the Collector tab) and Phase 6 (consolidate deploy dirs, v3.0.0). Multi-arch builds are dropped (single-arch is fine).
5. Supplemental (not core): OTel Demo leftovers and the Android app live in `plans/supplemental/` (`otel-demo-and-demo-apps.md`, `android-shop-app-plan.md`): unblocked; start with M0 (behaviour spec + API contract against the OTel Demo `/api/*` routes). Clean-room rules in that plan still apply.

## Open decisions for the owner

* Directory consolidation for v3.0.0 (Phase 6) — still unconfirmed.
* `origin` is `https://github.com/tinyolly/tinyolly` (the upstream org repo). The modernization work is merged into `main`; core images were pushed to Docker Hub on 2026-11-10 (demo images not rebuilt). No release tag yet.
