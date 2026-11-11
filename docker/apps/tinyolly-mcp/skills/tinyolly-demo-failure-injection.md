---
name: tinyolly-demo-failure-injection
description: Use when the user runs the OpenTelemetry Demo (Astronomy Shop) with TinyOlly and wants to inject a failure with a feature flag and watch or investigate its effect ("break payments", "make the shop slow", "show how TinyOlly catches errors").
---

# Inject a failure and investigate it

Needs the OTel demo running (`docker-otel-demo/01-start-otel-demo.sh`) with TinyOlly core up. Flags are set with `docker-otel-demo/03-set-flag.sh`; use the Bash tool only if the user asked you to run it, otherwise show the command.

## Flow

1. **Baseline:** `list_services(format="table")`. Note error rates and p95 for `payment`, `checkout`, `cart`, `frontend`.
2. **Inject** (from `docker-otel-demo/`): `./03-set-flag.sh paymentFailure 50%` (list flags with `./03-set-flag.sh`; others: `cartFailure`, `productCatalogFailure`, `imageSlowLoad 5sec`, `adHighCpu on`). flagd hot-reloads it.
3. **Wait 30-60 s** for traffic, then run the `tinyolly-triage` playbook. Expected for `paymentFailure`: `payment` and `checkout` error rates rise; error traces show checkout returning 422 `PAYMENT_FAILED`.
4. **Show the effect:** `chart_service_map("checkout")` (red node on the payment path) and `get_trace(<error trace>, format="waterfall")`.
5. **Optional, apply a collector preset in the TinyOlly UI** (Collector tab): `sampling` keeps every error trace while dropping most healthy ones; `pii-redaction` pairs with the `emitRawPii` flag (check `get_span` attributes before and after).
6. **Reset:** `./03-set-flag.sh --reset`. Say you did.

## Notes

- `paymentFailure` and `emitRawPii` effects are verified; other flags are expected behaviour from the flag descriptions. Say so when reporting unverified ones.
- Flags that need Kafka, the AI agent or flagd-ui are not available in this 16-service subset. See `read_doc("otel-demo")`.
- Do not use `loadGeneratorFloodHomepage` on an 8 GB machine without watching memory.
