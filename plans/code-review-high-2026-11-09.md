# Code review (high) — TinyOlly platform, passes H1–H6

Date: 2026-11-09 · Effort: high, report-only, six scoped passes (see `plans/code-review-highs.md`). Demo apps/generators, docs, plans, `site/` excluded.
Reviewers read code only; **"Verified" means I reproduced it** (live stack, sqlite, grep). Everything else is the reviewer's reading, not yet tested.
Origin: **ours** = introduced by this modernization work; **existing** = was in the repo before.

## Verified by me (reproduced)

| ID | Pass | Finding | Origin | Evidence |
|---|---|---|---|---|
| V1 | H2 | **Size trimming can wipe retained data.** `PRAGMA auto_vacuum=INCREMENTAL` is set *after* `journal_mode=WAL` on a new DB, so it stays 0 and `incremental_vacuum` frees nothing; `_get_db_size` uses `page_count` (includes free pages), so size never falls after a trim and the 60 s cleanup keeps deleting once the DB crosses the high-water mark | existing | sqlite test: `auto_vacuum` reads 0 after WAL-then-set; code reads `page_count * page_size` with no freelist subtraction (`storage_sqlite.py` lines 72–77, 344–354) |
| V2 | H3 | OpAMP REST API sends `Access-Control-Allow-Origin: *` (line 353), no auth: any web page can POST a config to all collectors (simple request, content type not enforced) | existing | grep |
| V3 | H3 | `s.currentConfig = req.Config` (line 311) is written without `configMu`/`agentsMu` while `handleGetConfig` reads it → data race | existing | read lines 289, 311 |
| V4 | H3 | `otlptracehttp.WithEndpoint(endpoint[7:])` blindly strips 7 chars: `https://…` breaks, values shorter than 7 chars panic at startup | existing | grep line 423 |
| V5 | H4 | `POST /api/opamp/config` accepts any parseable YAML, including the scalar `42`, and queues it for the collectors (HTTP 200). No otelcol validation, no mapping check, no size limit | existing | live POST (I then restored the default config; collector unaffected) |
| V6 | H5 | The 5 MB ingest cap trusts `Content-Length`: a 6 MB `Transfer-Encoding: chunked` body is accepted (200). The Content-Length path does reject (413) | existing | live request |
| V7 | H1 | `prometheus-remote-write` preset has `processors: [batch]` only, so applying it drops `memory_limiter`/`resourcedetection`, and its debug exporter is still `detailed` | ours (preset predates the baseline; I did not update it) | grep |
| V8 | H6 | `build/dockerhub/03-push-all.sh` / `02-build-all.sh` call `push-core.sh`, `build-*.sh` etc. that do not exist (files are `03-push-*.sh`, `02-build-*.sh`) | existing | `ls` vs script |
| V9 | H6 | `docker/04-cleanup-images.sh` (and `docker-core-only/`) `sed 's/KB\/1024/'` is malformed → total size always `0.0MB` | existing | read line 42 |
| V10 | H6 | `k8s-core-only/01-deploy.sh` prints `http://localhost:5002`; on kind the UI is `:5005` | ours (minikube→kind edit incomplete) | grep |
| V11 | H6 | `docker/03-force-rebuild.sh` (and similar) have no `cd "$(dirname "$0")"`: run from another directory, `compose down` fails but the script continues to `volume rm` and `builder prune` | existing | read |

## Reported by reviewers, not yet reproduced

**H6 shell scripts**
* `k8s/03-cleanup.sh`, `02-deploy-tinyolly.sh`, `04-rebuild+deploy-ui.sh`, `k8s-core-only/*` act on **whatever kubectl context is current** (deletes Deployments/Services/ConfigMaps and the `tinyolly-db` PVC); context is only checked for the image-removal prompt. (**ours**: needs a `kind-tinyolly` guard.)
* `k8s/04-rebuild+deploy-ui.sh`: `set +e`, failed `kind load` is ignored and the pod is deleted anyway; prints success; no cd to own dir. (ours)
* `k8s/03-cleanup.sh` image removal hard-codes `tinyolly-control-plane`/`kind-tinyolly`, ignores `KIND_CLUSTER`, prints success regardless. `scripts/kind-up.sh` also ignores `KIND_CLUSTER`, doesn't check `kind`/`kubectl`/docker context. (ours)
* `build/dockerhub/*` unset `DOCKER_TLS_VERIFY` etc. but not `DOCKER_CONTEXT`; `03-push-core.sh` verifies `:latest` but pushes `:$VERSION`; unquoted vars. (ours/existing)
* `docker/04-cleanup-images.sh`: `grep -E 'tinyolly|demo-frontend|demo-backend'` is a substring match on the shared Colima daemon (could remove unrelated images). (existing, matters more now that the daemon is shared with kind)
* `scripts/test-collector-configs.sh`: absolute path arguments break (`$PWD/$f`), no trap to remove the container on Ctrl-C. (ours)

**H1 collector presets**
* `connectors-routing`: **failover never triggers** — the shared `otlp` exporter keeps its default `sending_queue`/retry, so the primary pipeline never errors synchronously; the backup is `debug` only, so failed-over data would be discarded anyway; routing at `context: span` splits one trace across the two pipelines; header says "never sampled" but the preset has no sampler. (ours)
* `sampling`: logs thinned to 25 % regardless of severity (drops 75 % of ERROR logs) and independent of the trace decision (breaks log↔trace correlation for kept traces). (ours)
* `logs-dedup`: folds identical logs from different traces into one record (loses trace_id/span_id); no condition to keep ERROR/FATAL or trace-bearing logs; header names the attribute `log_count`, config emits `dedup_count`. (ours)
* `connectors-metrics`: `signaltometrics` has no resource/datapoint attributes (all services in one series); `count` described "by status" but only has `service.name`. (ours)
* `transform-ottl`: health-check regexes are unanchored prefixes (`/healthcare` is dropped, `/live`/`/liveness` missed); body-keyword severity over-matches ("no exception", "error rate=0"); `filter/noise` runs before JSON flattening. (ours)
* `pii-redaction`: URL-secret regex misses `api_key=`, `key=`, `password=`, `sig=`, `X-Amz-Signature`; "bearer" in prose over-matches; Amex 4-6-5 grouping and Mastercard 2221–2720 not covered; `attributes/pii` hash/delete not applied on metrics. (ours)

**H2 storage** (existing unless noted)
* Per-table independent trimming leaves orphaned `trace_index`/`span_index` rows; `metrics_names`/`metrics_meta`/`kv` deleted by `expires_at` while series remain.
* `store_spans` writes every span blob into `traces` too and `traces.data` is never read (≈2× write cost).
* `get_service_catalog` decodes up to 10,000 span blobs *before* checking its kv cache; `get_service_graph` doubles it.
* N+1 connections: `get_trace_summary` per trace (5,000 for `limit=5000`), `get_span_details` per id; each call opens a new connection + 7 PRAGMAs.
* `get_attr_value` returns the first *attribute* whose key matches, not the first *preferred key*; `http.status_code` may be a string `"500"`, so `_get_service_red_metrics` misses string/numeric error codes (unlike the new `is_error_status`). (error-status part is the same family as the bug fixed in Phase 4)
* Ids base64-decoded unconditionally (hex ids from non-protobuf OTLP/JSON clients decode to garbage; malformed id 500s the batch); metric exemplar trace ids stay base64 while spans are hex, so exemplar→trace links cannot resolve (relevant to the Phase 5 exemplar work).
* `store_metrics` = one connection + transaction per datapoint under the global write lock; `max_cardinality`/`dropped` counters are read but never written, so cardinality protection does nothing and `metrics_dropped` is always 0.
* Cleanup task has no shutdown path; cleanup holds the write lock across the whole trim.

**H3 OpAMP server (Go)** (existing)
* `connToAgent` only filled when the agent record is created → on reconnect the new connection is unmapped: status flaps/stuck "connected"; stale agents are targeted.
* Pending config is deleted before delivery and `RemoteConfigStatus` is never inspected: no retry, no applied/failed tracking; `ConfigHash` is a timestamp, not a content hash.
* Config only queued for agents connected at POST time; new/reconnecting agents never get `currentConfig`; targeted POST overwrites the fleet-wide `currentConfig`; unknown `instance_id` returns 200.
* No request body size limit and no YAML check on `POST /config`.
* `handleStatus` encodes live `AgentState` pointers after unlocking (race); `handleGetConfig` holds `RLock` across network writes.
* No auth on port 4320/4321; arbitrary `InstanceUid` takes over an agent record; the response never sets `ReportFullState` or advertises capabilities.
* `http.Server` without timeouts; no graceful shutdown; `log.Fatalf` skips the deferred telemetry shutdown.
* Dockerfile: runtime image runs as root, no `USER`/`HEALTHCHECK` (though `/health` exists), extra bash/coreutils.

**H4 validate/apply endpoints** (existing)
* `validate` runs `otelcol-contrib validate` on user YAML with the full UI process environment; confmap `${env:…}`/`${file:…}` references can be expanded and may be echoed in error output. (My probe with `${file:/etc/hostname}` returned `valid: true` and no content; echo-on-error leakage is not demonstrated.)
* Blocking `subprocess.run(timeout=10)` inside an `async` handler freezes the event loop.
* Whole OpAMP router unauthenticated (`/docs` exposed); `instance_id` interpolated into the URL without encoding; only `aiohttp.ClientError` caught (timeouts → 500); error messages leak internal hosts/paths/temp file names.
* Validation fails open: timeout/missing binary/exception → `basic_validation`, which can return valid and can itself crash on non-mapping YAML.
* `template_id` joined into a path without a containment check (currently limited by route/suffix); CORS default `http://localhost:*` is matched literally by Starlette (does nothing), with credentials enabled.

**H5 ingest** (existing)
* No type/size validation of parsed JSON (wrong types → 500, huge attribute counts/nesting); alert webhooks are fired serially, per error span, inside the ingest request with no dedup; alert rules unauthenticated (SSRF via `webhook_url`).
* `/v1/traces` (JSON) stores raw spans and does not use `parse_otlp_traces`: resource attributes/`serviceName` lost, ids stay base64; `/v1/logs` ignores `resourceLogs`.
* gRPC receiver: no `maximum_concurrent_rpcs`, `future.result()` without timeout, `MessageToDict` on the shared loop, unchecked `add_insecure_port`, raw exception text returned.
* WebSocket manager mutates a set while iterating; `/ws/updates` and the service-map/catalog reset endpoints are unauthenticated (cross-site simple POST can wipe them).
* Request-metrics middleware labels by raw path → unbounded cardinality from scanners.

## Suggested priority (my judgment, not the reviewers')

| Priority | Items | Why |
|---|---|---|
| P0 small, high value | V1 (trimming), V6 (chunked cap), V2+V5+V3+V4 (OpAMP API: remove `*` CORS, require JSON, validate config on apply, lock `currentConfig`, parse endpoint with `url.Parse`), k8s context guard | data loss / remote config takeover / easy DoS; each is a few lines |
| P1 | V7–V11, the rest of H6 (rebuild/cleanup scripts), preset fixes (routing/failover, sampling logs, dedup keep-errors, signaltometrics attrs, transform regex anchors, pii regex gaps) | correctness of things we shipped; several presets do not do what their blurbs claim |
| P2 | Storage perf (N+1, catalog decode, per-datapoint transactions), cardinality enforcement, hex/base64 id handling, ingest validation, OpAMP reconnect/ack tracking | real but larger design work; fold into Phase 5 / trace-accuracy work |
| P3 | Dockerfile hardening, websocket manager, middleware cardinality, gRPC limits | hardening |

Security-flavoured items (V2, V5, H4 auth/leakage, H5 SSRF/webhooks, unauthenticated reset endpoints) deserve a dedicated `/security-review` before any public release; the product is a local dev tool, so binding to localhost by default may be the pragmatic fix.
