# TinyOlly Otel Shop — Android App (clean-room, OTel SDK)

Date: 2026-11-09 · Status: draft · Companion to `2026-11-modernization-plan.md` (Phase 4 shop, Phase 3 collector presets)

## Goal

An Android (Kotlin/Jetpack Compose) shopping app that drives the TinyOlly demo shop and shows
**real mobile → backend distributed traces, logs and metrics** in TinyOlly, using only the
**OpenTelemetry Android SDK** (no bitdrift SDK, no bitdrift backend).

## Reference & clean-room rules

Inspiration: `bitdriftlabs/sa-public/misc-demos/bitdrift-shop-opentelemetry` (Android + iOS clients over the OTel Demo "Telescope Store").

Clean-room means we reproduce *observable behavior and structure*, not code, assets or names.

- **Used as spec input (read already):** the repo README/Android README (public docs) and the file tree only. Source files were **not** read.
- **Do not** read, copy or port its Kotlin, Compose UI, theme, drawables, scripts, workflows or dashboards. Don't copy package name (`com.example.shoppingdemo` / `ai.bitdrift.oteldemo`), class names, or the telemetry event names verbatim where a standard OTel name exists.
- Write our own **behavior spec** (`docs/mobile/app-spec.md`) first, from the list below; implement from the spec only.
- Own app name **TinyOlly Otel Shop**, package `io.tinyolly.otelshop`, own icons and visual design, own copy.

### Structure observed (to mirror conceptually)

| Reference element | Our equivalent |
|---|---|
| Single Gradle app module, Compose, one `Screen` sealed set, simple nav (transitions disabled to keep captures lean) | Single module `mobile/android/app`, Compose Navigation, same minimal-transition choice |
| Layers: API client, app lifecycle callbacks, screen logger, simulation manager, recommendation helper, theme | `data/ApiClient`, `telemetry/*`, `sim/SimulationManager`, `ui/*` |
| ~18 screens: Welcome, Browse, Search, Featured, Categories, CategoryBrowse, ProductDetail, Reviews, Cart, Wishlist, CheckoutGuest, CheckoutSignIn, Payment (card / Apple Pay / PayPal / Android Pay), PaymentFailed, Confirmation | Same journey; payment variants reduced to card / wallet / invoice-style; keep a failure screen |
| Welcome screen has **Sim 5 / Sim 10 / Sim ∞** + cancel banner; one journey = one session | Same idea (our own UI): scripted synthetic journeys with presets |
| Feature flags set per session (checkout flow, payment UI, cart-abandon rate, ANR variant) | OTel feature-flag attributes; same "variants per session" concept |
| Failures: cart failed, checkout failed, payment failed + retry with another method, ANR simulation | Same failure classes, injected via backend chaos flags and client-side |
| Backend: OTel Demo frontend proxy `/api/*`, emulator reaches host at `10.0.2.2` | Our shop API (see below); same `10.0.2.2` default, configurable |
| Scripts: setup, start emulator, build+install+launch, stop | Our own `mobile/android/scripts/`, **no Android Studio/IDE** (see Tooling) |
| Local, gitignored config file with host/port | `local.properties`-style `.local.properties` (own keys) |

## Backend choice: mini shop first, full OTel Demo optional

Recommendation: **the Python shop from modernization Phase 4 is the mini version**, and it exposes a REST surface shaped like the OTel Demo frontend (`/api/products`, `/api/products/{id}`, `/api/cart`, `/api/checkout`, `/api/recommendations`, `/api/currency`, `/api/shipping`, `/api/data`) so the app works against either. Verify the exact OTel Demo routes/payloads at implementation time.

- Mini shop: ~5 Python services + Postgres, fits comfortably in a Colima VM with TinyOlly; owns the failure injection the mobile sim needs.
- Full OTel Demo: optional Helm install on the kind cluster (existing `k8s-otel-demo` script, re-pointed at the TinyOlly collector); heavier (needs a much bigger VM), so not the default.
- API contract lives in `docs/mobile/api-contract.md` (OpenAPI from the FastAPI service) — the app is built against the contract, not a specific backend.

## Telemetry design (OTel only)

SDK: **opentelemetry-android** (agent + instrumentations) on top of OTel Java SDK, export **OTLP/HTTP** to the TinyOlly collector (`http://10.0.2.2:4318`; LAN IP for physical devices). Pin versions; the Android agent is young, so check stability/API of the pinned release at implementation time.

| Concern | Approach |
|---|---|
| Resource | `service.name=tinyolly-otel-shop-android`, `service.version`, `deployment.environment`, `device.*`, `os.*` (semconv), `telemetry.sdk.*` |
| Sessions | SDK session provider → `session.id` on all signals; new session per simulated journey |
| Screen views | One span per screen (`screen.view`, attr `screen.name`) plus a navigation event; manual, via a Compose nav listener |
| Journey | Root span `shop.journey` (attrs: flow variant, outcome) with screen spans as children; span **links** between journeys of the same user |
| Network | OkHttp instrumentation → client spans, **W3C `traceparent`** injected so backend spans join the same trace (mobile is the true root) |
| Logs | OTel log records with `event.name` for user actions (`add_to_cart`, `checkout_failed`, `payment_retry`, …); standard names where semconv exists |
| Feature flags | `feature_flag.key` / `feature_flag.variant` attributes (+ evaluation events), also as resource/session attrs |
| Metrics | journeys started/completed/failed counters, screen-render and API-latency histograms (exponential), cart-value gauge |
| Crashes / ANR / slow render | Agent's crash, ANR and slow-rendering instrumentations; a simulated ANR and crash trigger for demos |
| Lifecycle | App start/foreground/background spans from the agent's activity instrumentation |
| Config | Endpoint/headers/sampler from `.local.properties`; head sampler ratio configurable (pairs with the `tail_sampling` preset) |
| Exceptions | Span events with `exception.*` for handled API/payment errors |

## What TinyOlly / collector need to support this

- **Collector** (Phase 3): mobile preset — `transform` to normalize screen/session attrs, `filter` noise, `redaction` for PII in attributes the app deliberately sends (email/card tail), `tail_sampling` keeping failed journeys, `servicegraph` showing app → frontend → services, `spanmetrics` split by `screen.name`.
- **UI/API gaps** (Phase 5): a Sessions/Journeys view grouping by `session.id`; screen-path timeline for a session; surface `device.*`/`os.*`/`app.version`; trace map handles a mobile root (inferred client is the app, not an orphan); log ↔ trace links for event logs; crash/ANR list from exception events. Confirm what already works before building.
- Networking: kind `extraPortMappings` / Colima port forwards must expose 4318 and the shop API on the host so `10.0.2.2` from the emulator reaches them.

## Tooling: CLI only, no IDE (decided)

Emulator-only for v1. Everything runs from scripts, same style as the demo `0N-*.sh` scripts:

| Script | Does |
|---|---|
| `android-1-setup.sh` | Install cmdline-tools/platform-tools/emulator/system image via `brew` + `sdkmanager`; create AVD with `avdmanager`; check JDK; accept licenses |
| `android-2-start-emulator.sh` | Boot AVD (`EMULATOR_WINDOW=0` for headless), wait for `sys.boot_completed` |
| `android-3-start-app.sh` | `./gradlew installDebug` + `adb shell am start`; reads `.local.properties` |
| `android-4-stop-app.sh` | `adb shell am force-stop` |
| `android-5-stop-emulator.sh` | `adb emu kill` |

- Gradle wrapper only; no IDE project files committed. Debug builds only (no signing).
- Apple Silicon: arm64-v8a system image with hardware acceleration; check it coexists with Colima.
- Emulator reaches host services at `10.0.2.2` (collector 4318, shop API).

## Phases

| # | Phase | Deliverable | Effort |
|---|---|---|---|
| M0 | Clean-room spec | `app-spec.md` (screens, flows, events, failure modes, sim presets) and `api-contract.md`; no reference source consulted | 1 d |
| M1 | Backend contract | Shop API implements contract incl. chaos flags (`latency`, `error`, `payment_decline`); contract tests | 1–2 d (rides on modernization Phase 4) |
| M2 | App skeleton | Gradle/Compose project, nav, all screens against real API, own design | 3 d |
| M3 | OTel instrumentation | SDK wiring, resource, sessions, screen/journey spans, OkHttp + traceparent, logs, metrics, flags, crash/ANR | 3 d |
| M4 | Simulation + failures | SimulationManager (5/10/∞ + cancel), per-session flag variants, cart abandon, payment failure/retry, ANR/crash toggles | 2 d |
| M5 | TinyOlly support | Mobile collector preset, UI gaps above, demo tour section ("follow one tap to the DB") | 3 d |
| M6 | Tooling, CI, docs | the five CLI scripts above, unit + instrumented smoke test, CI build, README + screenshots | 2 d |

M0 can start immediately and runs in parallel with modernization Phases 1–3. M3–M5 need the Phase 3 collector baseline and Phase 4 shop.

## Verification (per phase, acceptance)

- Emulator headless run of 10 simulated journeys → TinyOlly shows ≥10 distinct `session.id`s, each trace with a mobile root span and backend child spans under one trace ID.
- Injected payment decline shows `payment_failed` log, error span with exception event, and the retry path; failed journeys survive `tail_sampling`.
- PII attribute is masked by the redaction preset.
- Fresh-machine run documented: Colima + kind + Android emulator, one script each.

## Decisions

- App name: **TinyOlly Otel Shop** (`io.tinyolly.otelshop`).
- **Emulator-only** for v1; run entirely via scripts, no IDE. Physical devices deferred.
- SDK: **`opentelemetry-android` agent**; hand-wire the Java SDK only where the agent has gaps.
- Out of scope: iOS.

## Still open

- Visual identity/palette (quick design pass; must not resemble the reference).
- Min/target SDK and Kotlin/Compose/AGP versions: pick current at implementation time.
