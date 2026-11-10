# Supplemental: OpenTelemetry Demo and demo apps

Split out of `2026-11-modernization-plan.md` (2026-11-10). This is demo work, not the core TinyOlly product. It is optional and can proceed independently. The Android app plan lives next to this file: `android-shop-app-plan.md`.

## Status

- Done: the upstream OpenTelemetry Demo (16-service subset) runs against TinyOlly (`docker-otel-demo/`, docs in `docs/otel-demo.md`). Verified flags: `paymentFailure`, `emitRawPii`.
- Not done / unverified:
  - the other flagd flags listed in `docs/otel-demo.md`;
  - the Helm path (`k8s-otel-demo/`, chart 0.42.6, needs a VM of 6 GB or more because the chart deploys Kafka);
  - the eBPF demo under Colima `vz`;
  - the AI-agent demo on the Python 3.13 locks and its GenAI semconv review;
  - replacing the hand-rolled Prometheus remote-write v2 client;
  - the 5-minute demo tour doc (`docs/demo-tour.md`).
- Open decision: keep the Flask `docker-demo` apps? They stay useful for ad-hoc preset tests (PII, duplicate-log spam, cardinality).

## Original Phase 4 plan (superseded by the upstream demo)

Replace the two-service Flask demo with a small multi-service "shop" (single compose + single k8s manifest, one code base per language, shared load generator):
- Python-only (decided): `web` (Flask/FastAPI), `cart`, `payments`, `inventory` (Postgres via SQLAlchemy), `worker` (Redis/RabbitMQ or Kafka consumer), `loadgen` (Locust or k6 with scenario profiles).
- Real dependencies: Postgres, Redis (as a demo dependency only), a queue → DB spans, messaging spans with span links, `db.*` and `messaging.*` semconv.
- Failure injection endpoints/flags (`/chaos?mode=latency|error|leak`) driven by loadgen schedule so there is always something interesting: error bursts, slow dependency, retry storms, cardinality bomb (for protection demo), PII in attributes (for redaction demo), duplicate log spam (for logdedup).
- Signals: exponential histograms, exemplars, gauge/UpDownCounter, runtime metrics, structured logs with trace correlation, baggage propagation, span events + exceptions, span links.
- Keep: eBPF/OBI variant (pinned image), AI agent variant. Upgrade AI agent: use current GenAI semconv (`gen_ai.*` incl. agent/tool spans), multi-step agent with tool calls, token usage metrics, and evaluate a small current Ollama model; pin Ollama.
- Replace hand-rolled Prom RW v2 with a maintained approach or document why kept; keep one Prometheus-scrape path (`prometheus` receiver) in the demo.
- Demo "tour" doc: `docs/demo-tour.md` — 5-minute script mapping each preset to what to click.

## Phase 4 execution log (2026-11-09)

Decision: the custom 6-service Python shop is dropped. `docker-otel-demo/` runs a 16-service subset of the upstream demo (tag 3.1.0, `OTEL_DEMO_VERSION` in `versions.env`) against TinyOlly's collector. Branch `modernize/phase-4-otel-demo` (stacked on phase 3).
- Measured on the 8 GB Mac: demo (16 services + 3-user Locust, browser traffic off) + TinyOlly = ~1.06 GB containers, ~1.57 GB used in the 4 GB Colima VM. Fits.
- Scripts: `01-start-otel-demo.sh` (clone pinned tag, `DEMO_VERSION` pinned to the tag, `OTEL_COLLECTOR_HOST=host.docker.internal`, `--no-deps` so the demo's own collector is not started), `02-stop-otel-demo.sh [--purge]`, `03-set-flag.sh` (edits flagd's file; hot-reloaded). `docs/otel-demo.md` has the flag ↔ preset tour.
- **Gotchas found:** (1) the demo `.env` has `DEMO_VERSION=latest`; images from `main` do not match the 3.1.0 compose (new `recommendation` image lacks `nc` → healthcheck fails) — pin it; (2) Java services default to http/protobuf, so pointing them at :4317 logs "port is likely incorrect" warnings (only seen on the unhealthy `latest` image; none after pinning).
- **TinyOlly bug found and fixed by this demo:** spans arrive with status code `STATUS_CODE_ERROR` (string) but the storage layer only recognised `2`, so Service Catalog showed 0 % errors and the trace list never flagged errors. Fixed (`is_error_status`), added trace `has_error`/`error_count` (the demo's load-generator root span has no status, so root-only detection missed every failure), UI badges use `spanStatusLabel`. Verified: payment 65 %, checkout 19 % error rate under `paymentFailure=100%`. 3 regression tests added.
- Verified end to end: `paymentFailure` (errors visible), `emitRawPii` + `pii-redaction` preset (email/card masked). The demo's raw CVV (`demo.payment.card_cvv`) leaked through the first version of the preset → added `.*cvv.*`, `.*cvc.*`, `.*card[_.]?number.*` key patterns; re-verified masked.
- Dropped from original Phase 4: custom Postgres/Redis/queue services and the loadgen scenario profiles, "cardinality bomb" and "duplicate log spam" failure modes (not in the upstream demo; `docker-demo` Flask apps remain for ad-hoc presets), Kafka/messaging spans + span links (Kafka consumers are not in the 16-service subset; they need ~1.1 GB more — possible stretch via `compose.full.yaml`).
- Not done / untested: Helm path (`k8s-otel-demo/`, chart 0.42.6 pinned, load generator trimmed; chart needs Kafka so ≥ 6 GB VM); flags other than the two verified; eBPF + AI-agent variants unchanged (AI agent GenAI-semconv upgrade not done); Prom RW v2 replacement not done.
- Android plan: its "mini Python shop first" backend choice is obsolete — the app should target the OTel Demo frontend `/api/*` (reachable at `10.0.2.2:8080` from the emulator, which this setup already exposes).
