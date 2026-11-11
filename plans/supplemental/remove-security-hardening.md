# Plan: remove security hardening

**STATUS: EXECUTED 2026-11-10** (sections 1-4 and 6; 5 and 8 deliberately kept). Left as a record of what was removed and why; to restore, see commit `6c93a93` (Origin guard, webhook validation, gRPC limits) and `5daac59` (OpAMP write token). Section 7: docs had no remaining references except this plan.

**Decision (owner, 2026-11-10):** TinyOlly only runs locally on a Mac for observability demos. Security hardening is not wanted. See also the "Security-flavoured items" note in `plans/code-review-high-2026-11-09.md`.

**Rule when executing:** remove only what exists for security. Several items below look like hardening but protect functionality (they stop the demo wedging or the DB growing without bound). Those are marked **KEEP**. Run `./scripts/test-all.sh --stack` after each step; the e2e suite is the safety net.

## 1. UI: Origin guard and CORS regex (remove)

Added in commit `6c93a93`. Blocks cross-site browser writes with 403. Risk of keeping it: it can reject legitimate local use (a different hostname, a tunnel, another port).

- Delete `docker/apps/tinyolly-ui/app/core/origin.py`.
- `app/core/middleware.py`: remove the `origin_guard` middleware and the `origin_allowed` / `cors_origin_regex` imports; make CORS `allow_origins=["*"]` (or drop CORS handling entirely).
- `app/routers/system.py`: remove the `origin_allowed` check in the websocket handler (around line 109).
- `app/config.py`: remove `cors_origins` and `allowed_origins`.

## 2. UI: OpAMP write token (remove)

- `app/config.py`: remove `opamp_api_token`.
- `app/routers/opamp.py`: remove the `Authorization: Bearer` header (around line 251).
- `docker/apps/tinyolly-opamp-server/main.go`: remove `apiToken`, `OPAMP_API_TOKEN`, the `requireToken` wrapper (around lines 82, 106, 551, 717-725) and the JSON content-type-only check (around line 397, it exists to defeat cross-origin `text/plain` posts). Update `main_test.go` to match.

## 3. Webhook validation (remove)

- `validate_webhook_url` and the check in `add_rule` (UI alerts service) block private and loopback targets (SSRF protection). This also blocks webhooks to other local services, which is the main local use case.
- Keep the **background cooldown delivery** (webhooks must not block ingest) and the cooldown itself.

## 4. Generic error details (remove)

- OTLP receiver returns generic gRPC error details instead of exception text. Return the real exception message instead, which is more useful for debugging locally.
- Keep the request timeout / deadline handling (`_run_async` timeout, `DEADLINE_EXCEEDED`).

## 5. Request size and rate limits (decide per item)

- `app/core/request_limits.py` (body-size limit on ingest): size limits double as protection against a runaway exporter filling the SQLite DB. **KEEP unless it rejects real demo payloads**; if it does, raise the limit rather than remove it. The MCP-style large-trace case (a few MB) must still ingest.
- gRPC receiver `MAX_WORKERS`, `MAX_CONCURRENT_RPCS`, `MAX_MESSAGE_BYTES` (receiver around lines 77-79, 167-172): **KEEP** workers and concurrency (they bound threads and fds); raise `MAX_MESSAGE_BYTES` if large batches are rejected.
- OpAMP server `maxConfigBodyBytes` and UI `MAX_CONFIG_CHARS` (1,000,000): **KEEP**, harmless.
- Cardinality limit and DB size cap / trim in `tinyolly_common`: **KEEP** (functionality: bounded memory and disk).

## 6. Tests to delete or trim

- `docker/apps/tinyolly-ui/tests/test_hardening.py`: **delete these**: `test_origin_allowed`, `test_custom_pattern_and_regex`, `test_cross_site_post_to_api_is_blocked_but_curl_is_not`, `test_admin_writes_are_guarded_and_ingest_is_exempt`, `test_validate_webhook_url`, `test_add_rule_rejects_bad_url`. **Keep** (functionality, only housed in this file): `test_metric_endpoint_label_is_the_route_template`, `test_broadcast_survives_set_mutation_during_iteration`, `test_webhooks_do_not_block_and_are_rate_limited`, `test_numeric_error_status_still_alerts`, `test_admin_stats_serialises_fractional_percent_and_reset_clears`. Rename the remaining file to `test_ui_behaviour.py`.
- `docker/apps/tinyolly-otlp-receiver/tests/test_receiver_hardening.py`: delete `test_errors_return_generic_details_not_exception_text`; keep the timeout and caller-thread tests; rename to `test_receiver_behaviour.py`.
- `docker/apps/tinyolly-ui/tests/test_ingest_limits.py` / `test_ingest_validation.py`: read each test first; keep those that check the data is parsed correctly, drop ones asserting 4xx for hostile input only.
- OpAMP Go tests for the token and content-type check.

## 7. Docs and plan cleanup

- `docs/api.md` (CORS/Origin notes), `docs/ebpf.md` and `k8s-demo-ebpf/ebpf-agent.yaml` security mentions (the eBPF agent needs privileged mode to work; that is not hardening, leave it).
- `plans/code-review-highs.md` item 3 (`/security-review`) and H4/H5 auth/SSRF wording; `plans/code-review-high-2026-11-09.md` V2/V5; `plans/2026-11-modernization-plan.md` PII row refers to the **pii-redaction collector preset**, which is a demo feature, **KEEP**.
- `plans/HANDOFF.md`: update the P2 description.

## 8. Not security, leave alone

- The collector `pii-redaction` preset (a demo feature about telemetry content).
- `scripts/lib/kubectx.sh` and `scripts/test-kubectx-guard.sh`: this stops scripts from touching a non-kind cluster (protects the user's real clusters from the demo scripts). Keep.
- The non-root user and healthcheck in the OpAMP image (healthcheck is functional).

## Done when

`./scripts/test-all.sh --stack` passes, a cross-origin request and a request with a webhook to `http://localhost:*` both work, and `grep -rniE "origin_allowed|apiToken|OPAMP_API_TOKEN|validate_webhook" docker/` finds nothing.
