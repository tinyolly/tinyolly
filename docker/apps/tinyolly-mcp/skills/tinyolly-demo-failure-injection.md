---
name: tinyolly-demo-failure-injection
description: Use when the user runs the OpenTelemetry Demo (Astronomy Shop) with TinyOlly and wants to inject a failure with a feature flag and watch or investigate its effect ("break payments", "make the shop slow", "show how TinyOlly catches errors").
---

# Inject a failure and investigate it

Needs the OTel demo on kind (`k8s-otel-demo/01-deploy-otel-demo-helm.sh`) with TinyOlly running. Flags are set by the user in the demo's panel: run `kubectl port-forward svc/frontend-proxy 8080:8080`, then open http://localhost:8080/feature.

## Flow

1. **Baseline:** `list_services(format="table")`. Note error rates and p95 for `payment`, `checkout`, `cart`, `frontend`.
2. **Inject:** ask the user to set `paymentFailure` to `50%` in the panel (others: `cartFailure`, `productCatalogFailure`, `imageSlowLoad` `5sec`, `adHighCpu` `on`). It applies at once.
3. **Wait 30-60 s** for traffic, then run the `tinyolly-triage` playbook. Expected for `paymentFailure`: `payment` and `checkout` error rates rise, with error traces.
4. **Show the effect:** `chart_service_map("checkout")` (red node on the payment path) and `get_trace(<error trace>, format="waterfall")`.
5. **Optional, apply a collector preset in the TinyOlly UI** (Collector tab): `sampling` keeps every error trace while dropping most healthy ones; `pii-redaction` pairs with the `emitRawPii` flag (check `get_span` attributes before and after).
6. **Reset:** have the user set the flag back to `off`.

## Notes

- `paymentFailure` and `emitRawPii` effects are verified; other flags are expected behaviour from the flag descriptions. Say so when reporting unverified ones.
- The `lean` size profile has no Kafka or AI components, so their flags have no effect there. See `read_doc("kubernetes")`.
