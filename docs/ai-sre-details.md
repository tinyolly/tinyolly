---
title: "AI SRE Details"
description: "Model setup, the console, the demo shift and its scoring, how the TinyOlly AI SRE Agent decides, and its limits"
---

# AI SRE Details

## Model and network

The default is a model on your LAN: built and tested with Qwen3.8 27B (q4, MTP) on one RTX 5090 box running Ollama.

[![How the pieces fit: the OpenTelemetry Demo and TinyOlly on a Mac, the model on a GPU box](images/ai-sre-local-setup.svg)](images/ai-sre-local-setup.svg)

If the agent cannot reach a model on your LAN, restart Colima from your own Terminal app (macOS grants local network access per app):

```bash
colima stop -p tinyolly && ./scripts/colima-up.sh
```

On the demo's flags, the shift uses the `flagd-ui` API inside the cluster, so changes apply at once.

## Choose a model

| Preset | Default model | Enable it |
|---|---|---|
| Local (Ollama), **default** | `qwen3.8:27b-mtp-q4_K_M` | `SRE_LLM_URL` (any OpenAI-compatible endpoint) and `SRE_MODEL` on `k8s/06-rebuild+deploy-sre.sh` (pass them on every run) |
| OpenAI | `gpt-5` (`SRE_OPENAI_MODEL`) | `OPENAI_API_KEY` in the secret below |
| Claude | `claude-opus-5-5` (`SRE_ANTHROPIC_MODEL`) | `ANTHROPIC_API_KEY` in the secret below |

Configured presets appear in the console's model picker; switching applies to the next investigation. `SRE_PRESET=claude` (or `openai`) starts on a cloud preset. Put the keys in a secret: `kubectl create secret generic tinyolly-sre-llm --from-literal=ANTHROPIC_API_KEY=...`. Claude uses the official SDK with refusal fallbacks (`ANTHROPIC_EFFORT`, default `medium`). Cloud presets send telemetry excerpts (span and service names, error messages) to the provider; the local default keeps everything on your network.

## The console

[![Console, light theme: live investigation stream on the left, investigations on the right](images/ai-sre-console-light.png)](images/ai-sre-console-light.png)

- **Live stream** (left): every step as it happens: signals, evidence, prompt, tool calls and results, finding. Click a line for the full text.
- **Investigations** (right): a list with each incident's name, status and cause. An incident is named after the signal that opened it, then renamed after its cause once concluded. Click one for the full investigation:
    - **Triage:** `act now`, `watch` or `noise`, and whether it **would page** (shadow mode: nothing is paged; the shift report scores it).
    - **Conclusion** with confidence, and the **theories** considered: confirmed ✓, ruled out ✗ with the deciding fact, or open.
    - **Evidence trail:** the cited trace and every query the agent ran; each chip opens that view in TinyOlly, and hovering shows the result.
    - **Timeline:** related change marker, detection, new symptoms, investigation, conclusion, fix, recovery.
    - Blast radius, proposed fixes, recovery result and time to resolve.
    - **Write postmortem:** a blameless draft (summary, impact, timeline, root cause, theories, 5 whys, evidence, action items) to copy or download as markdown.
- **Ask** (bottom): free-form questions about your telemetry. Answers take the agent's unresolved and recent incidents into account. Asking never opens an investigation; only a detector does.


## Demo shift

The demo shift flips [OpenTelemetry Demo feature flags](scenarios.md) on a timer, so problems come and go. All flags reset to `off` on start, stop and exit.

The agent is never told what was injected. It finds problems from telemetry alone. `DEMO_ANNOUNCE=1` also publishes each flip as a **change marker** (`flag paymentFailure: off -> 50%`) it can read with `what_changed`, as a real flag system would.

| Scenario | Flag | What the agent should find |
|---|---|---|
| `payment-degraded` | `paymentFailure=50%` | checkout errors; the cause is payment |
| `payment-down` | `paymentUnreachable=on` | hard dependency outage |
| `cart-flaky` | `cartFailure=25%` | partial errors seen by several callers |
| `ad-failure` | `adFailure=on` | errors in one service |
| `slow-images` | `imageSlowLoad=5sec` | frontend latency, cause upstream (needs browser traffic: `PROFILE=full`) |
| `slow-shipping` | `intlShippingSlowdown=5sec` | latency on one path only |
| `catalog-lock` | `productCatalogLockContention=on` | latency from the database |
| `catalog-bad-product` | `productCatalogFailure=on` | errors on one product only |
| `recommendation-cache` | `recommendationCacheFailure=on` | slow path, subtle |
| `traffic-flood` | `loadGeneratorFloodHomepage=on` | load, not a bug: capacity |
| `quiet` | none | **control**: the agent should open nothing |

Scenarios are data: `docker/apps/tinyolly-sre/sre/scenarios.json`.

- **Order:** random (never the same fault twice in a row, a quiet period every 4 faults; `DEMO_SEED` makes it repeatable), or fixed for a rehearsed demo: `DEMO_SCRIPT=payment-degraded,slow-shipping,quiet k8s/06-rebuild+deploy-sre.sh --demo` (the shift ends with the script).
- **Controls:** `POST /demo/start`, `/demo/pause`, `/demo/stop`, `/demo/reset` (all flags off), `/demo/trigger` with `{"id": "slow-images"}`. `GET /demo/status` shows what runs; the header shows only `demo: running · next fault in 2:40`, so the room does not see the answer first.
- **Scores:** **Reveal scores** marks each investigation against the injected fault: `correct` (service and cause), `partial`, `wrong`, `false positive`, `no answer`; faults with no incident count as missed. `GET /demo/report` is the shift report: counts, paging decisions, time to detect and resolve, tool calls and tokens. Samples are small, so it gives counts, not percentages.

**Profiles.** **Quick** is the default: a scenario takes about 2 minutes (all 11 in about 25).

| | Quick (default) | Realistic (`--realistic`) |
|---|---|---|
| Faults | stronger variants (`paymentFailure=90%`, `cartFailure=75%`, `10sec` slowdowns), 75-90 s each | the variants in the table above, 4-6 min each |
| Between faults | 30 s cooldown and a clean cutoff (earlier telemetry is ignored), 20-30 s gap | 2.5-3 min cooldown for errors to age out, 1-2 min gap |
| Shop load | the size profile's (15 or 40 users) | the same |
| Detection | every 5 s; error rate, rate and p95 from the last 30 s of spans | every 30 s; rate and p95 from the service catalog |
| Change notes | off (the model stays free for investigations) | a change-risk note and a post-change check per flip |

To tune without waiting, record a shift once (`SRE_RECORD=/tmp/shift.jsonl`) and replay it through the detectors in seconds or the model in minutes: see "Fast iteration" in the [agent's README](https://github.com/tinyolly/tinyolly/tree/main/docker/apps/tinyolly-sre).

## How it decides

Detectors run without a model: error spans, error rate (per service and per operation), p95 latency, traffic drop or surge, a service that stops reporting, error logs, high CPU, failing health checks, container restarts (Kubernetes), mesh denials, and TinyOlly's storage pressure. Errors are attributed to the service where they start, so separate faults stay separate incidents. Each service learns its normal; a change must hold for two polls. Signals on a service and its direct callers or callees join one incident, investigated from the deepest service. Settings are in the [agent's README](https://github.com/tinyolly/tinyolly/tree/main/docker/apps/tinyolly-sre).

**Guardrails:** at most 8 tool calls and 120 s per investigation, 12 investigations an hour, read-only tools (not TinyOlly's docs or playbooks, which describe the demo's faults), and cited traces and services are kept only if they appeared in the evidence.

## Limits

- Synthetic faults are not production; a good score says little about real incidents.
- `imageSlowLoad` only affects real browsers. Without browser traffic (the lean profile) it leaves nothing to detect.
- With `--realistic`, several faults leave too little signal at the demo's low traffic to detect.
- Two unrelated faults close together can merge into one incident through a shared caller such as `frontend`.
- One model run at a time: a review can delay an investigation by up to a minute.
