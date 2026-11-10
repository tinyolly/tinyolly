# Handoff — TinyOlly modernization (2026-11-09)

Everything needed to continue on another computer. Read this first, then `plans/2026-11-modernization-plan.md` (status table + execution log).

## Where things are

* **Branch flow:** `v3-integration` was merged into `main` on 2026-11-10 (PRs #8–#13) and deleted. All work is on `main`; there are no open PRs or side branches (besides `gh-pages`). For new work, branch from `main` and open PRs into `main`.
* The phase branches were stacked and are no longer needed (they were local-only except `modernize/phase-4-otel-demo`, which is merged). For reference, the phase boundaries were: phase 0 `bef08a0`, phase 1 `4ba7eab`, phase 2 `d90f300`, phase 3 `3327ed2`, phase 4 `cc524eb`+.
* Commit author used throughout: `Steve Lerner <stevelerner@gmail.com>` (no git identity was configured on the original machine; set your own with `git config user.name/email` before committing).
* Plans: `plans/2026-11-modernization-plan.md` (main), `plans/2026-11-trace-accuracy-plan.md` (next work), `plans/2026-11-android-shop-app-plan.md` (not started).

## RESUME HERE (session stopped mid-work, 2026-11-10)

**Open PRs:** none.

**Work in progress: branch `fix/p1-review-findings`** (pushed, **no PR opened yet**; it already contains #9/#10/#11 content, stacked on `fix/p0-review-findings` plus a merge of `fix/review-medium-findings`, so its diff shrinks as those merge). It holds the P1 preset fixes from `plans/code-review-high-2026-11-09.md` (H1) and is a **work in progress**:

| Preset / item | Change | State |
|---|---|---|
| `sampling` | WARN+ logs always kept; every log gets a sampling key (trace id, else a UUID) because the sampler **dropped every log without a trace id**; temp attributes deleted after | **verified** by `scripts/test-preset-behavior.py sampling` (5/5) |
| `logs-dedup` | only INFO/DEBUG logs with no trace id are deduped (`trace_id == TraceID(0x00..00)`; `trace_id.string == ""` does not work) | **verified** (4/4) |
| `connectors-routing` | failover now real: `otlp/primary` with queue+retry disabled, backup = `file` exporter (`/var/lib/otelcol/failover-traces.jsonl`) instead of `debug`; header corrected | starts OK, **behaviour test written but never run** |
| `transform-ottl` | anchored probe-path regexes, JSON `level` -> severity, uppercase-token body rule, flatten runs before the debug filter | starts OK, **behaviour test not run** |
| `pii-redaction` | more URL secret keys, 16+ char bearer tokens, Amex 4-6-5, Mastercard 2221-2720 | starts OK, **behaviour test not run** |
| `connectors-metrics` | `signaltometrics` keeps `service.name`; separate `tinyolly.span.error.count` | starts OK, **behaviour test not run** |
| `prometheus-remote-write` | baseline `memory_limiter`/`resourcedetection` added, debug `basic` | starts OK, not behaviour-tested |

Next steps for P1, in order:
1. `python3 scripts/test-preset-behavior.py transform-ottl pii-redaction connectors-metrics connectors-routing` (needs Colima + docker, ~3 min; stack not required). The script's log/metric parsers were only exercised on sampling and dedup, so a failure may be a test bug rather than a preset bug: read the debug output before changing a preset. Fix what fails, then open a PR for `fix/p1-review-findings` into `v3-integration`.
2. DONE on `fix/p1-review-findings` (H6 script fixes: build-all/push-all names, cleanup size + anchored image greps, cd to own dir, :5005, kind-load failure aborts, KIND_CLUSTER honoured, dockerhub pins colima context and verifies the pushed tag, test-collector-configs absolute paths + trap). Previously listed as not started: `build/dockerhub/03-push-all.sh` / `02-build-all.sh` call scripts that do not exist; `docker/04-cleanup-images.sh` malformed `sed` and unanchored image grep; `docker/03-force-rebuild.sh` (and similar) no `cd` to own dir before `volume rm`; `k8s-core-only/01-deploy.sh` prints `:5002` (should be `:5005`); `k8s/04-rebuild+deploy-ui.sh` ignores a failed `kind load`; `build/dockerhub/*` do not pin the docker context; `scripts/kind-up.sh` ignores `KIND_CLUSTER`.
3. P2 DONE on `fix/p2-review-findings` (stacked on p1; PR into `v3-integration`): hex+base64 id normalization, preferred-key attribute lookup, batched metric writes + enforced `max_cardinality` with `metrics_dropped`, batched trace/span reads, catalog cache before decode, no more `traces` double write, orphan cleanup, storage `close()` on shutdown, OTLP JSON ingest through the shared parsers + 400 on wrong shapes, OpAMP reconnect remap / fleet config for late agents / content hash + ack-failure tracking / 404 unknown instance / optional `OPAMP_API_TOKEN` / graceful shutdown / non-root image. **Not verified live** (unit + `-race` tests only): no end-to-end run against a real supervisor, so run the stack and apply a preset to confirm `config_status` goes pending → applied. P2 leftovers also DONE on the same branch: WebSocket broadcast snapshot, route-template metric labels, Origin guard on all non-ingest writes and the WebSocket (CSRF) + real CORS regex, webhook URL validation (http(s), no link-local/metadata, no redirects) with background cooldown-limited delivery and string/numeric error status, gRPC receiver timeouts/concurrency cap/message cap/generic errors/worker-thread conversion/SIGTERM. (The `validate` endpoint was already fixed in P0.) Owner decision (2026-11-09): security is NOT a priority (local Mac demos only), so P3 hardening, gRPC TLS, auth and the `/security-review` are dropped. Focus on functionality: live end-to-end verification of the stack, Phase 5 UI gaps, trace-accuracy plan, Android app.
4. (dropped: `/security-review`, see owner decision above)

**Lessons from this stretch (also in the code):**
* The routing preset test once named a container `tinyolly-receiver`-style after a real service; `docker rm -f <name>` would have deleted the real one. The script now requires test containers to be named `pt-*` and uses `--network-alias` on a private network. Never name test containers after real ones.
* `scripts/test-collector-configs.sh` mounts a writable `/var/lib/otelcol` (the supervisor image has it, the plain contrib image does not).
* A verification probe once posted a junk config to the live `/api/opamp/config`; use fakes or the standalone-collector tests, not the live collector, for destructive probes.
* Debug exporter output uses `ResourceLog #n` (singular) for logs, `ResourceSpans`, `ResourceMetrics`.

**State of the original machine (not in git):** Colima VM `tinyolly` running with the core stack, the OTel Demo (16 services) and a rebuilt UI/receiver/opamp image; the demo flag `emitRawPii` may still be `on` and the `sampling`/`default` collector config may be applied. None of this matters on another machine; `./scripts/colima-up.sh && (cd docker && ./01-start-core-local.sh)` recreates it.

## Automated end-to-end test (added 2026-11-10)

`python3 scripts/e2e.py` drives a RUNNING stack only through its APIs (stdlib only, ~8 min, 88 checks): baseline pipeline (traces/logs/metrics/exemplars/service map/catalog), the OpAMP apply flow, and every collector preset with behaviour assertions. `--up` starts Colima + the stack first, `--only a,b` / `--list` select scenarios. **After changing `tinyolly-common` rebuild the base image first** (`docker build -t tinyolly/python-base:latest -f docker/dockerfiles/Dockerfile.tinyolly-python-base docker/`): `docker compose --build` does not rebuild it, so the UI/receiver silently keep the old library (this hid fixes for a while).

Test hooks added for it: `POST /admin/reset` (delete all telemetry), `POST /api/opamp/config?wait=N` (returns per-agent applied/failed + `config_hash`), `config_status`/`applied_config_hash` in `/api/opamp/status`.

Bugs the e2e run found and fixed: `/admin/stats` 500 once any metric existed (`percent_used` float vs int model); `database is locked` drops of whole receiver batches (writes now `BEGIN IMMEDIATE` + `busy_timeout` set before WAL + retry with backoff); **exponential histograms were silently dropped** (now converted to explicit buckets at ingest).

## Set up a new machine (macOS)

```bash
brew install colima docker docker-compose docker-buildx kubectl kind helm uv
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
* Phase 4: only `paymentFailure` and `emitRawPii` (+ `pii-redaction`) were verified; the other flags in `docs/otel-demo.md` are expectations. Helm path (`k8s-otel-demo/`, chart 0.42.6) untested and needs ≥ 6 GB because the chart deploys Kafka.
* UI visual checks: the user tested the UI visually (service map, charts after the Chart.js/Cytoscape bumps) and reported it fine; the sticky-header fix was deployed but not re-checked by eye.
* Tests: 136 of the UI tests are placeholder `pytest.skip` stubs. Lint was fixed: `ruff.toml` has an explicit rule set; use `ruff==0.17.4` (defaults change between releases). The receiver has no tests (CI only byte-compiles it). The `ui`/`receiver` CI jobs have not run on GitHub at all.
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
4. Phase 5 UI gaps (exemplar→trace links, span events/exceptions pane, span links, processor-effect panel on the Collector tab) and Phase 6 (consolidate deploy dirs, buildx multi-arch with a `docker-container` builder, v3.0.0).
5. Android app (`plans/2026-11-android-shop-app-plan.md`): unblocked; start with M0 (behaviour spec + API contract against the OTel Demo `/api/*` routes). Clean-room rules in that plan still apply.

## Open decisions for the owner

* Directory consolidation for v3.0.0 (Phase 6) — still unconfirmed.
* Whether to keep the Flask `docker-demo` apps now that the OTel Demo exists (they remain useful for ad-hoc preset tests: PII, duplicate-log spam, cardinality).
* `origin` is `https://github.com/tinyolly/tinyolly` (the upstream org repo). The modernization work is merged into `main`; core images were pushed to Docker Hub on 2026-11-10 (demo images not rebuilt). No release tag yet.
