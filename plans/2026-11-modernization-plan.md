# TinyOlly Modernization Plan

Date: 2026-11-09 · Last commit: 2026-04-22 (v2.3.0) · Status: Phase 0 done (branch `modernize/phase-0-baseline`)

## Goals

1. Bring all dependencies, images, and the collector stack fully up to date.
2. Demo the important modern OTel Collector processors/connectors, with visible effect in the UI.
3. Make the telemetry demo richer and more realistic.
4. Replace Docker Desktop with **Colima** as the container runtime and Minikube with **kind** (upstream Kubernetes) running on Colima.

## Review findings

### Stack / structure
- 3 Python services (UI FastAPI, OTLP receiver, `tinyolly-common`), 1 Go service (OpAMP server), collector wrapped by OpAMP Supervisor. SQLite storage (README/docs still partly describe Redis).
- 5 near-duplicate deployment trees: `docker/`, `docker-core-only/`, `docker-demo/`, `docker-demo-ebpf/`, `docker-ai-agent-demo/`, plus 5 matching `k8s*` trees. `docker/` and `docker-core-only/` overlap heavily; the ebpf demo copies `app.py`, `backend-service.py`, `remote_write_pb2.py` from `docker-demo/`.
- `site/` holds built mkdocs output checked into the repo.

### Staleness / risks
- **Unpinned images**: `otel-supervisor` builds from `collector-contrib:latest` and `opampsupervisor:latest`; `otel/ebpf-instrument:main`; `ollama:latest`; all tinyolly images `:latest` with `pull_policy: always`. Builds are non-reproducible and a collector release can silently break the supervisor config.
- **Go**: `go 1.22`, `opamp-go v0.18.0`, otel-go `v1.32.0`. All well behind. `go mod tidy` runs inside the Dockerfile (hides drift).
- **Python**: all deps are floors (`>=0.42b0`, `>=1.22.0`, `>=0.45b0`) with no lockfile; base image `python:3.12-slim`; CI tests on 3.11 (mismatch with runtime). `docker-demo` and `ebpf` use different OTel floors than core.
- **Collector config**: only `batch` processor; no `memory_limiter`, no resource detection. `spanmetrics` dims use legacy attrs `http.method` / `http.status_code` (semconv renamed to `http.request.method` / `http.response.status_code`). `debug` exporter at `detailed` verbosity on every pipeline is noisy. `--feature-gates service.AllowNoPipelines` workaround should be re-checked.
- **Semconv**: demo apps and UI queries likely key off old HTTP attribute names and old `gen_ai.*` names; GenAI semconv has moved considerably.
- **Collector `templates/incorrect.yaml`** is a deliberate bad example living next to real templates; only one real template (`prometheus-remote-write.yaml`) exists, so the "config templates" feature is thin.
- **Redis leftovers**: `k8s/redis.yaml`, `docs/redis-archive.md` while storage is SQLite.
- **Runtime coupling to Docker Desktop/Minikube**: `docker-compose` (v1 binary) in scripts, `minikube image load` flows in `build/local/*`, README says "Tested on Docker Desktop and Minikube". Colima is installed here (0.10.3) but not running; `docker`, `kubectl`, `minikube` present.
- **Demo gaps**: 2 Flask services with random sleeps; no DB/queue/messaging, no errors with meaningful structure, no sampling/redaction story, single-signal-flavour per service. The AI agent demo uses a single `tinyllama` call loop. Prometheus remote write v2 is hand-rolled (`prom_remote_write_v2.py`, vendored pb2).
- **Tests**: UI has good unit coverage; OTLP receiver partial; no tests for Go server, collector config validity, or demo end-to-end. CI doesn't build images or validate configs.

## Plan (phased; each phase = a PR)

### Phase 0 — Baseline (1 PR, small)
- Branch, run existing tests locally, record results in this file.
- Pin current versions into a single `versions.env` (collector, supervisor, ollama, redis removal, python, go) as the source of truth consumed by Dockerfiles/compose/k8s.
- Remove dead Redis artifacts; stop committing `site/` build output (build in CI to gh-pages).

### Phase 1 — Colima runtime (1 PR)
- Add `scripts/colima-up.sh`: `colima start --cpu 4 --memory 8 --disk 60 --vm-type vz --vz-rosetta` (profile `tinyolly`), sets `docker context use colima-tinyolly`, verifies `docker info`.
- Replace `docker-compose` v1 calls with `docker compose` (v2) everywhere; add a preflight helper `scripts/lib/preflight.sh` that checks Colima running, arch, and free resources, shared by all `01-*.sh` scripts.
- Kubernetes: use **kind** on Colima (real upstream k8s, same cluster type as CI). Drop `--kubernetes` from the Colima start. Add `kind-config.yaml` (extraPortMappings for 5005/4317/4318, optional 2 workers for `k8sattributes`/DaemonSet demos) and `scripts/kind-up.sh`. Replace `minikube image load` flows in `build/local/*` with `kind load docker-image`. Update `k8s*/` scripts and docs accordingly (`docs/kubernetes.md`, `docs/docker.md`, `build/README.md`, README platform line).
- eBPF demo: confirm OBI works in Colima VM (`privileged`, `pid: host`) — needs a Linux kernel with BTF; verify under `vz`; document fallback.
- Replace `host.docker.internal` usage if any (Colima supports it, verify).
- Acceptance: from a clean machine with `brew install colima docker docker-compose kubectl kind helm`, `./scripts/colima-up.sh && docker/01-start-core-local.sh` yields working UI on :5005.

### Phase 2 — Dependency & image refresh (1–2 PRs)
- Python: move to 3.13 (check uvloop/grpcio wheels), adopt `uv` with lockfiles (`uv.lock`) per service; bump FastAPI, uvicorn, pydantic, OTel SDK/instrumentation to current; align CI Python version with image.
- Go: bump to current stable, `opamp-go` and otel-go latest; commit `go.sum` after tidy; drop `go mod tidy` from Dockerfile; add `go vet`/`go test` to CI.
- Pin collector-contrib and supervisor to the same explicit release tag (check latest at execution time); re-verify supervisor config keys against that release's schema (supervisor config has changed across releases).
- Pin base images by tag (+ digest in release builds); drop `pull_policy: always` for pinned versions.
- Re-verify the frontend JS libs (Cytoscape, dagre, charting) and bump.
- Add Dependabot/Renovate config for pip, gomod, docker, actions.
- Update spanmetrics and demo apps to current HTTP/DB semconv attribute names; add a UI compatibility shim for old names so existing user data still renders.

### Phase 3 — Collector processors showcase (1–2 PRs)
Ship a layered default config plus **named presets** selectable from the Collector tab (via OpAMP), each with a short "what this does" blurb and a before/after view in the UI. Validate every preset in CI with `otelcol-contrib validate`.

Baseline (always on): `memory_limiter` → `resourcedetection` (env, system, docker) → `batch`.

| Preset | Components | What the demo shows |
|---|---|---|
| Sampling | `tail_sampling` (keep errors, slow >500ms, 10% probabilistic), `probabilistic_sampler` for logs | Trace count drop, errors always retained; sampling %, `sampling.priority` |
| PII / security | `redaction` (allowed keys, blocked value regexes for emails/cards/tokens), `attributes` hash/delete | Masked `user.email`, `http.url` query secrets in UI |
| Transform / OTTL | `transform` (normalize route names, set severity from body, flatten JSON log bodies, add `deployment.environment`), `filter` (drop health checks, debug logs) | Cleaner logs, dropped noise counts |
| Enrichment | `k8sattributes` (k8s tree), `resource`, `groupbyattrs`, `geoip` (demo with synthetic client IPs) | Service/pod/namespace attributes, geo on spans |
| Metrics shaping | `cumulativetodelta` / `deltatocumulative`, `interval`, `metricstarttime`, `filter` for metrics, `metricstransform` | Temporality conversion, cardinality reduction (ties to `CARDINALITY-PROTECTION.md`) |
| Logs | `logdedup`, `transform` severity mapping, `filelog` receiver in demo | Deduped repeated errors w/ counts |
| Connectors | `spanmetrics` (updated attrs, exemplars on), `servicegraph`, `count`, `signaltometrics`, `routing` (errors → separate pipeline), `failover` | Service graph from servicegraph vs UI-derived map; RED metrics with exemplars linking to traces |

Notes / to verify at execution time: which of these are beta/alpha in the pinned release (`metricstarttime`, `signaltometrics`, `logdedup`, `geoip`), stability flags, and whether OTLP **profiles** signal is worth a stretch goal (receive + show count only). Remove the legacy `debug: detailed` default → `basic`, with a toggle.
- Make `incorrect.yaml` an explicit "validation demo" under `templates/examples/` and add ≥6 real templates (one per preset above).
- Collector tab: ensure effective-config + health from supervisor surface processor-level stats (collector internal telemetry on :8888 scraped into TinyOlly; show accepted/refused/dropped per processor).

### Phase 4 — Better telemetry demo (2 PRs)
Replace the two-service Flask demo with a small multi-service "shop" (single compose + single k8s manifest, one code base per language, shared load generator):
- Python-only (decided): `web` (Flask/FastAPI), `cart`, `payments`, `inventory` (Postgres via SQLAlchemy), `worker` (Redis/RabbitMQ or Kafka consumer), `loadgen` (Locust or k6 with scenario profiles).
- Real dependencies: Postgres, Redis (as a demo dependency only), a queue → DB spans, messaging spans with span links, `db.*` and `messaging.*` semconv.
- Failure injection endpoints/flags (`/chaos?mode=latency|error|leak`) driven by loadgen schedule so there is always something interesting: error bursts, slow dependency, retry storms, cardinality bomb (for protection demo), PII in attributes (for redaction demo), duplicate log spam (for logdedup).
- Signals: exponential histograms, exemplars, gauge/UpDownCounter, runtime metrics, structured logs with trace correlation, baggage propagation, span events + exceptions, span links.
- Keep: eBPF/OBI variant (pinned image), AI agent variant. Upgrade AI agent: use current GenAI semconv (`gen_ai.*` incl. agent/tool spans), multi-step agent with tool calls, token usage metrics, and evaluate a small current Ollama model; pin Ollama.
- Replace hand-rolled Prom RW v2 with a maintained approach or document why kept; keep one Prometheus-scrape path (`prometheus` receiver) in the demo.
- Demo "tour" doc: `docs/demo-tour.md` — 5-minute script mapping each preset to what to click.

### Phase 5 — Product/UI gaps surfaced by the demo (as time allows)
- Exemplar → trace link in Metrics tab; span links view; exponential histogram rendering check; span events/exceptions pane; GenAI-specific view polish; processor-effect panel on Collector tab.
- Consider MCP/AI-friendly API docs refresh (`docs/api.md`) and OpenAPI examples.

### Phase 6 — CI & release (1 PR)
- CI uses kind for a k8s smoke test.
- CI: matrix test on pinned Python, Go tests, `otelcol-contrib validate` for every config/template, `docker compose config` + `kubectl kustomize/--dry-run` linting, multi-arch image build (amd64/arm64) with buildx, smoke test (compose up, send OTLP via `telemetrygen`, assert API returns trace/log/metric).
- Consolidate duplicated deploy dirs: single `deploy/compose/` with profiles (`core`, `demo`, `ebpf`, `ai`) and `deploy/k8s/` with kustomize overlays; keep thin shims/redirect notes for old script paths for one release.
- Cut **v3.0.0** (breaking: path layout, pinned versions, Colima-first); write release notes; update README/docs/site.

## Order & effort (rough)

| Phase | Effort | Depends on |
|---|---|---|
| 0 Baseline | 0.5 d | – |
| 1 Colima | 1–2 d | 0 |
| 2 Refresh | 2–3 d | 0 |
| 3 Processors | 3–4 d | 2 |
| 4 Demo | 4–5 d | 1, 3 |
| 5 UI gaps | 2–3 d | 4 |
| 6 CI/release | 2 d | all |

Phases 1 and 2 can run in parallel.

## Open decisions

- Consolidating the directory layout (Phase 6) is the largest user-visible change; confirm it's wanted for v3.0.0 vs. keeping current paths.
- Decided: demo is Python-only for now; Kubernetes is kind on Colima (k3s is the fallback).
- Exact version pins (collector, supervisor, OTel SDKs, Go, Python) must be looked up at execution time; nothing here was verified against upstream release notes.

## Execution log

### Phase 0 (2026-11-09)
- Baseline (Python 3.13 venv, local Mac): `tinyolly-ui` tests **2 passed, 136 skipped** ("SQLite storage not yet implemented") — effective coverage is near zero. `tinyolly-otlp-receiver` has **no `tests/` dir**, so its CI job fails. Both to fix in Phase 2/6.
- Added `versions.env` (collector+supervisor 0.165.0, ollama 0.40.15, OBI v1.0.0, Python 3.13, Go 1.27); tags verified to exist on ghcr/Docker Hub. Wiring into Dockerfiles is Phase 2.
- Removed Redis artifacts: `k8s*/redis.yaml`, `docs/redis-archive.md`, `storage.py`, `redis` dependency, `RedisStorage` export.
- Untracked `site/` (already gitignored). CI gh-pages build still TODO (Phase 6).
- Not done: colima/docker not on PATH in this shell (Phase 1 prerequisite).

### Phase 1 (2026-11-09) — in progress
- Host is a **8 GB / 8 core Mac**: plan's `--memory 8` would starve the host, so `scripts/colima-up.sh` defaults to 4 CPU / 4 GB (override `COLIMA_MEMORY`). Brew installed docker, docker-compose (plugin enabled via `~/.docker/config.json`), kubectl, kind, helm.
- Done: `scripts/colima-up.sh`, `scripts/lib/preflight.sh` (not yet sourced by `01-*.sh`), `scripts/kind-config.yaml`, `scripts/kind-up.sh`; `docker-compose` → `docker compose` across scripts/docs.
- Verified: `docker/01-start-core-local.sh` on Colima (vz) builds (~1.5 min) and serves UI :5005 (200), collector connected to OpAMP.
- Verified: `kind-up.sh` creates a 1-node cluster (1.37.0).
- ~~TODO (done below)~~: k8s manifests use `LoadBalancer` (UI) — need NodePorts 30005/30317/30318 to match kind-config; replace `minikube image load` in `build/local/*` with `kind load docker-image`; source preflight in `01-*.sh`; verify OBI/eBPF demo under vz; docs (`kubernetes.md`, `docker.md`, README platform line).

#### Phase 1 — minikube → kind replacement (done)
- `build/local/build-*-minikube.sh` → `build-*-kind.sh` (build on Colima docker, `kind load docker-image`); ebpf demo images now tagged `tinyolly/ebpf-*` to match manifests.
- Services: UI → NodePort 30005 (host 5005), demo frontends → NodePort 30001 (host 5001), collector → NodePort 30317/30318; mapped in `scripts/kind-config.yaml`. No more `minikube tunnel`.
- `imagePullPolicy: Always` → `IfNotPresent` in `k8s/`, `k8s-core-only/` and ebpf demo (Always would pull stale Hub images over locally loaded ones).
- Rebuild/cleanup/deploy scripts, docs (kubernetes, ebpf, index, README, build/README) updated; zero `minikube` references remain outside release notes.
- Verified end-to-end: `build-core-kind.sh` → `k8s/02-deploy-tinyolly.sh` → 4 pods ready, UI :5005 = 200, OTLP/HTTP :4318 accepted, stats show data. NOT yet verified: k8s-demo, k8s-demo-ebpf deploy, cleanup scripts, `04-rebuild*` scripts, k8s-core-only. Existing kind cluster predates the 5001 mapping: recreate it (`kind delete cluster --name tinyolly`) before the demo.
