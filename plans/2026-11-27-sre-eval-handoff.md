# Handoff: SRE agent, docs and flagd scenario evaluation (2026-11-27, ~11pm)

Goal: evaluate the docs, the SRE agent and the flagd scenarios so the agent works as well as it can.

## State
* 11 changed files plus this one, **uncommitted, unpushed**. Docs site not published.
* kind cluster `kind-tinyolly`: demo and agent redeployed with these changes, all flags off, `DEMO=0` (no automatic shift). Console: `kubectl --context kind-tinyolly port-forward deploy/tinyolly-sre 7173:8080`.
* SRE tests: 51 pass (2026-11-28). Colima was stopped on 2026-11-28. Not run: `./scripts/test-all.sh`, strict docs build. Lint was already failing at HEAD (534 errors in `docker/apps/`, now at least 536, same one-line style).
* Recordings and shift reports (git-ignored): `docker/apps/tinyolly-sre/recordings/` (`*2026-11-27*`).

## Fixed today
* `k8s/06-rebuild+deploy-sre.sh --demo --realistic` always failed (set and removed `DEMO_PROFILE` at once).
* Go services (`checkout`, `product-catalog`) stopped seeing flag changes: `FLAGD_CACHE=disabled` in `k8s-otel-demo/{lean,full}.yaml`. A restart proved the staleness; the underlying cause is a hypothesis.
* `productCatalogFailure` targeting returned `off` on both branches: `sre/demo.py` now sets the targeting.
* New traffic surge detector (`DETECT_SURGE_FACTOR`, 4x and >= 5/s).
* A skipped re-investigation erased an earlier finding (`sre/core.py`). Unit-tested, not seen live.
* Docs: `imageSlowLoad` needs browser traffic (off on lean); removed from "Flags worth trying".

## Last live run (5 faults, realistic, before the erased-finding fix)
| Fault | Detected | Diagnosis |
|---|---|---|
| payment-degraded | 39s | correct |
| payment-down | 37s | correct |
| catalog-lock | 74s | first card wrong; second right but erased |
| catalog-bad-product | 24s | skipped (cap); raised on `frontend-proxy` |
| traffic-flood | 50s | skipped (cap) |

Plus 2 false positives before the first fault, right after a redeploy.
Not in that run: cart-flaky, ad-failure, slow-shipping, recommendation-cache (all correct in the earlier full run).

## Next
1. `MAX_INVESTIGATIONS_PER_HOUR` (12) runs out during a demo shift. Proposed: raise in demo mode for the local model only (cloud costs money). Not yet agreed with the user.
2. Fixed 2026-11-28, unit-tested, not seen live: `EventStream` spans no longer count toward p95.
3. Fixed 2026-11-28, not deployed: demo `opamp-server` re-enabled in `lean.yaml` (needs a demo redeploy).
4. Rerun `DEMO_SCRIPT=catalog-lock,catalog-bad-product,traffic-flood,quiet ./k8s/06-rebuild+deploy-sre.sh --build --demo --realistic`.
5. Docs pages not yet reviewed: everything beyond quickstart, otel-demo, ai-sre, ai-sre-details, scenarios.

## Gotchas
* Wait for old errors to age out (or clear telemetry) before a shift; leftovers caused 3 false positives.
* The agent pod has a 256Mi limit: don't run heavy scripts with `kubectl exec` inside it.
* A pod restart with `DEMO=1` starts a new shift. `SRE_RECORD` writes inside the pod: copy it out before redeploying.
* Replaying a quick-profile recording needs the `QUICK_ENV` values passed as `--set`.
* Replay needs `httpx`: use a venv with the agent's requirements.
* No browser tools were available in the session.
