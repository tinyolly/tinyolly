# TinyOlly SRE agent: test and documentation plan

Status: **not started** (written 2026-11-23). Code is in `docker/apps/tinyolly-sre/`, unit-tested only (7 tests), never run live.

## Part 1: Testing

### 1. Smoke (30 min) — does it run at all?
- [ ] Pull a model Ollama has (`qwen3:8b` or set `SRE_MODEL`); confirm `host.docker.internal:11434` is reachable from the container.
- [ ] Start core stack + `docker/05-start-sre.sh`; `/healthz` ok, console loads at :7173, log shows `tinyolly-sre up`.
- [ ] Fix whatever breaks first. Likely suspects: API field names guessed from code reading (`/api/spans` start time units, `/api/logs` timestamp/severity fields, `/api/service-map` edge keys, `/admin/stats` shape), MCP `initialize` handshake against `tinyolly-mcp`, `host.docker.internal` on Colima.
- [ ] `POST /ask` with a plain question: gets an answer, uses MCP tools.

### 2. Detector tests against the OTel demo (the real test)
Use `docker-otel-demo` with its failure injection. One row per detector; record time-to-detect and false positives during 15 quiet minutes first.

| Detector | Trigger | Pass |
|---|---|---|
| quiet baseline | 15 min, no faults | zero incidents, zero signals |
| errors / error-rate | flagd failure flag on a service | one incident, one investigation, cites a real trace id |
| latency | latency flag, or `tc`/sleep injection | `latency` signal, not before baseline (6 polls) |
| traffic | stop load-generator or scale a service to 0 requests | `traffic` signal |
| vanished | stop one service's container | `vanished` after 3 polls |
| logs | service that logs errors without failing spans | `logs` signal |
| mesh | Istio ambient demo, apply deny policy / add plaintext edge | `denied` / `plaintext` signal |
| platform | lower `MAX_DB_SIZE_MB`, or high-cardinality metric spam | `platform` signal |
| recovery | undo each fault | incident resolves in ~2 polls, `Recovered: yes` |

Tune: `DETECT_*` thresholds, `BASELINE_POLLS`, `CONFIRM_POLLS`. Known soft spots: the catalog is computed over the last 10,000 spans, so rate/p95 move slowly and may need a windowed calculation from `/api/spans` instead; `DETECT_IGNORE` list for the demo (flagd-style noisy services).

### 3. Behaviour tests
- [ ] Grouping: one fault that hits a service and its callers makes one incident, not several.
- [ ] Caps: force more than 12 incidents/hour and >30 notes/hour; confirm skips are logged, not queued forever.
- [ ] Reviews skip during open incident, warm-up and busy model (never delay an investigation).
- [ ] Change notes: `POST /api/events` a marker; get a change-risk note immediately and a post-change note at +150 s.
- [ ] Digest appears after the first history row; runbook follows each finding.
- [ ] Citation guard: model returns an invented trace id; finding falls back to the evidence's example id.
- [ ] Model failure modes: Ollama down (no crash, signals still logged), MCP down (falls back to evidence only), non-JSON answers (nudge, then `timeout`/`[no final answer]`).
- [ ] Restart: events already present at start are not re-noted; alerts at startup baseline.

### 4. Model comparison (optional, 1 hr)
Same faults with `qwen3:8b`, the 27B q4+MTP on navigator, and one hosted model. Score: correct service, correct cause, valid trace id, seconds, tokens. Pick the default from this.

### 5. Automated tests to add
- Detector tests with recorded API fixtures (capture real `/api/spans`, `/api/service-catalog`, `/api/logs`, `/api/mesh-posture`, `/admin/stats` JSON from the demo into `tests/fixtures/`).
- `run()` tests with a stub LLM for: tool loop, allowlist refusal, cap, timeout fallback, recovery path.
- HTTP handler tests (`/ask`, `/investigate`, `/events`).
- `tests/test_packaging.py` like the MCP app's: no `tinyolly_common` imports, Dockerfile builds with only this directory as context.
- Run script `run-tests.sh` + `install.sh` mirroring `tinyolly-mcp`.

### 6. k8s + packaging checks
- [ ] `k8s/06-rebuild+deploy-sre.sh` on kind; `LLM_URL` reaches the host Ollama from the pod (may need a different host address than `host.docker.internal`).
- [ ] `docker build docker/apps/tinyolly-sre` from a copied-out directory (the standalone claim).
- [ ] Compose without the `sre` profile is unchanged (`docker compose config` diff).

## Part 2: Documentation

- [ ] **App README** (`docker/apps/tinyolly-sre/README.md`): already has detectors, guardrails, run, standalone. Add after testing: measured time-to-detect table, tuned defaults, full env var reference, troubleshooting (model unreachable, no MCP, no signals during warm-up).
- [ ] **MkDocs page** `docs/ai-sre.md` + `mkdocs.yml` nav entry: what it is, quick start, console screenshots, sample finding / runbook / digest, how to read verdicts, limits.
- [ ] **Screenshots** into `docs/images/`: console mid-investigation, an expanded prompt/tool-call line, a finding and a review as change markers in the TinyOlly UI.
- [ ] **Root README**: the section exists; add a screenshot and the MCP-badge style link to the docs page.
- [ ] **MCP skills**: add `tinyolly-sre-findings.md` to `tinyolly-mcp/skills/` so Claude can read `ai-finding` / `ai-review` markers via `what_changed` / events (check the events tool exposes `kind`).
- [ ] **Backend authoring guide** (`docs/` or app README section): the `Backend` contract, a worked skeleton, how `SRE_BACKEND` selects it, so a standalone edition can add products.
- [ ] **Standalone split notes**: `git subtree split` recipe, what to rename (image `tinyolly/sre`), a root `LICENSE` copy, CI snippet.
- [ ] **Release notes** entry in `release-notes/`.
- [ ] **Demo script**: a 5-minute run sheet (inject fault, watch console, read finding, undo, see recovery) alongside the OTel demo docs.

## Order when resuming
1. Smoke (1), fix breakage. 2. Detector tests (2) with fixtures captured as you go (5). 3. Behaviour tests (3). 4. Tune defaults. 5. Docs (Part 2) using the real numbers and screenshots. 6. k8s/standalone checks (6), model comparison (4) if time.

## Open decisions
- Default model (`qwen3:8b` is a placeholder; only `llama3.1` is installed locally).
- Whether to build the skipped detectors: metric anomalies, collector/OpAMP health, version-split regressions.
- Whether to publish a `tinyolly/sre` image like the others (compose currently builds locally).
