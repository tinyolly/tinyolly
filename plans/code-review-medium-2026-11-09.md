# Code review (medium) — TinyOlly platform, merged diff `origin/main...origin/v3-integration`

Date: 2026-11-09 · Effort: medium, report-only · Scope: 105 platform files (see `plans/code-review-highs.md` for the scope rule; demo apps/generators, docs, plans, `site/`, lockfiles and generated ConfigMaps excluded).
The reviewer read the diff but **ran nothing**; the "Verdict" column is my follow-up check.

| # | File | Finding | Verdict | Action |
|---|---|---|---|---|
| 1 | `k8s/03-cleanup.sh:141` (same bug in demo `k8s-demo/03-cleanup.sh:111`) | `awk \'{...}\'` inside a double-quoted `sh -c` string leaves literal backslashes, so awk fails and `2>/dev/null \|\| true` hides it: "remove images from kind node" prints success but removes nothing | **Confirmed** (my minikube→kind conversion) | Fix: use a here-doc or escape properly; test with `crictl images` on a kind node |
| 2 | `scripts/test-collector-configs.sh:28` | Error filter drops lines containing `opamp`, `export`, `lookup`, `dial tcp`, so a real config error mentioning those words is hidden | **Valid, partly mitigated** (`validate` must pass and "Everything is ready" must appear, which a broken exporter would prevent) | Narrow the filter to the specific expected connection errors |
| 3 | `docker/otelcol-configs/templates/pii-redaction.yaml:44` | Card regex `\b(?:\d[ -]*?){13,16}\b` matches any 13–16 digit run (epoch-ns, numeric IDs) in all string attributes; redaction is not applied on the metrics pipeline | **Valid** (false positives expected; metrics gap is by design but undocumented) | Tighten the regex (Luhn-like formats / grouped digits) and document that metrics are not redacted, or add redaction to metrics |
| 4 | `docker/apps/tinyolly-opamp-server/main.go:179` | `AgentConfigFile` → `AgentConfigObject` may not exist in opamp-go 0.25 (reviewer could not check) | **False alarm**: `go build` and `go vet` pass on golang:1.27 (re-run today: `GO_BUILD_OK`) | None |
| 5 | `docker/dockerfiles/Dockerfile.otel-supervisor:2` | `versions.env` is not consumed by builds; versions are duplicated as Dockerfile `ARG` defaults | **Valid, known** (listed in HANDOFF as an open gap) | Add a drift check script or have compose/build scripts pass `--build-arg` from `versions.env` |
| 6 | `scripts/sync-k8s-configs.sh:22` | Drift between `docker/otelcol-configs` and the generated k8s ConfigMaps is no longer enforced anywhere now that CI is removed; single ConfigMap will approach the 1 MiB limit as presets grow | **Valid** (the enforcing CI step was deleted) | Run it in a local pre-commit/release checklist; split ConfigMap if it grows (currently ~30 KB) |
| 7 | `k8s/tinyolly-ui.yaml:19` | `:latest` + `IfNotPresent` and NodePort service only work on kind (images are `kind load`ed); stale `:latest` never refreshed | **Valid, accepted trade-off** (kind is the target; Hub images are pre-release) | Revisit with Phase 6 release tags |
| 8 | `docker/otelcol-configs/templates/sampling.yaml:60` | Might not override the base `traces` pipeline if the supervisor unions lists | **False alarm**: verified live that the preset replaces the base pipeline (47 of 400 OK traces kept, 30/30 errors kept). Logs sampling (25 %) is documented in `docs/collector-presets.md` | None |

## Summary

* Real defects: **#1** (confirmed bug), **#3** (regex too broad), **#2** (filter too broad). Maintenance gaps: **#5**, **#6**. Accepted: **#7**. False alarms: **#4**, **#8**.
* Suggested fix batch (small): #1 in both cleanup scripts, #2, #3 + docs note. Then re-run `./scripts/test-collector-configs.sh` and exercise the cleanup prompt on kind.
* `high` passes still open: see `plans/code-review-highs.md` (H1–H6); H6 (destructive shell scripts) is the most likely to find more bugs like #1.
