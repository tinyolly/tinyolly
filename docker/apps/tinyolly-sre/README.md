# tinyolly-sre

Generic AI SRE agent. Watches telemetry, groups failures into incidents, investigates each **once** with a model plus read-only MCP tools, then checks recovery when the signals clear.

## How it works
**Detectors** (no model call, every `DETECT_SECONDS`=30; pick with `DETECTORS`). Each signal names a service. Signals on one service, or on a direct caller or callee within `INCIDENT_GROUP_SECONDS` (180), join one incident, investigated from the deepest service. Error signals are first moved to the service where the failures start (the deepest failing span of sampled traces), so separate faults behind one caller stay separate incidents. A `traffic` or `vanished` signal joins its caller's error incident however old that is. The agent keeps the spans each poll returns for `SPAN_KEEP_SECONDS` (600), since the API returns only the newest 5000.

| Detector | Fires when |
|---|---|
| `errors` | >= 10 failing spans of one service in 2 min |
| `error-rate` | service error % (spans of the last 120 s, at least 3 errors; a service with < 10 spans there is measured over 360 s) >= 5 and 3x its learned normal, normal counted as at most 5% |
| `op-errors` | one operation (service + span name, e.g. frontend `GetAds`) failing >= 5% and 3x its own normal, with at least 3 errors in 3x the recent window: a failing dependency call hidden in a busy service |
| `latency` | p95 >= 3x its learned normal (and +100 ms) |
| `traffic` | request rate < 20% of normal, or >= 4x normal and >= 5/s (`DETECT_SURGE_FACTOR`) |
| `vanished` | a service that was reporting stops |
| `logs` | >= 10 error/fatal logs of one service in 2 min |
| `cpu` | a process at >= `DETECT_CPU_PCT` (40)% CPU in each of its last 3 runtime-metric samples |
| `health` | >= `DETECT_HEALTH_MIN` (6) failing health-check logs of one service in 6 min, spread over 2 min or more |
| `restarts` | a container restarted in the last 10 min, or is not ready (Kubernetes only: needs `k8s/tinyolly-k8s-state.yaml`) |
| `mesh` | new denied (403) or plaintext (non-mTLS) edge (Istio) |
| `platform` | TinyOlly's store >= 90% of its cap, or metric series dropped |

"Learned normal" is a per-service moving average; it needs `BASELINE_POLLS` (6) polls, a shift must hold `DETECT_CONFIRM_POLLS` (2) polls, and a problem is not learned as normal, except that a traffic or latency level held for `DETECT_HOLD_MAX_POLLS` (20) becomes the new normal (a baseline learned during a boot burst would otherwise keep an incident open forever); error rates are never re-learned. `DETECT_IGNORE` (names or globs, default `load-generator,tinyolly-*`) is skipped.

**Incidents:** settle `INCIDENT_SETTLE_SECONDS` (30), investigate once (plus `INCIDENT_REINVESTIGATE` (1) more time when a new kind of symptom joins a concluded incident, e.g. errors joining a traffic drop) (optional **runbook** note with up to 3 next steps: `RUNBOOK=1`; off by default because it repeated the card). After `INCIDENT_CLEAR_POLLS` (2) quiet polls it resolves and runs a recovery check (`Recovered: yes|no`, last minute, no tools).

**Notes with a model, own budget** (`REVIEW_MAX_PER_HOUR` 30; skipped during warm-up, while an incident is open, or while the model is busy):
- **Change-risk note** and **post-change check** (`CHANGE_CHECK_SECONDS` 150) for every new change marker (`CHANGE_NOTES`=1): blast radius from the service map, what to watch, then whether anything regressed.
- **Reviews** every `REVIEW_EVERY_SECONDS` (300), rotating: `shift-note`, `instrumentation-gaps` (services without logs or trace ids), `platform-health`, `mesh-posture`.
- **Digest** of the agent's own findings every 30 min (`DIGEST_EVERY_SECONDS`).
- Each note starts with `VERDICT: ok|watch|act` and is published as an `ai-review` marker.

**Guardrails:** `MAX_TOOL_CALLS` 8 (at the cap the model must answer from what it has), `DEADLINE_SECONDS` 120, `MAX_INVESTIGATIONS_PER_HOUR` 12, tool allowlist, `WARMUP_SECONDS` 60. Cited trace ids and services are kept only if they appeared in evidence or tool results.

**Output:** console at `:7173`, titled TinyOlly AI SRE Agent: a live investigation stream (click a line for prompts, replies and tool output), investigation cards with proposed fixes (never applied) and an ask box, in light and dark themes. Trace links point at `TINYOLLY_PUBLIC_URL` (`http://localhost:5005`), and `ai-finding` / `ai-review` change markers written back to TinyOlly (`POST /api/events`). `POST /investigate {"alert": "..."}`, `POST /ask {"question": "..."}`, `GET /events`, `GET /healthz`.

**Investigations API:** `GET /api/investigations` and `/api/investigations/{id}` return one record per incident: state (`open`, `investigating`, `concluded`, `recovering`, `resolved`), summary, root cause, confidence, evidence, blast radius, `suggested_fixes` (always `proposed`; nothing is applied), recovery result and time to resolve. `GET /stream` is server-sent events: the same lines as `/events`, typed (`detector`, `incident`, `thinking`, `tool_call`, `tool_result`, `finding`, `recovery`, `answer`, `note`, `investigation`), with the record in `data` for `investigation` events. Resume with `Last-Event-ID` or `?after=n`.

## Models
Presets (`sre/llm.py`), switchable at runtime from the console or `POST /api/models {"name": "claude"}`; `GET /api/models` lists them with reachability.

| Preset | Settings | Default |
|---|---|---|
| `local` (default) | `LLM_URL`, `MODEL`, `LLM_API_KEY`; any OpenAI-compatible endpoint | local Ollama, `qwen3.8:27b-mtp-q4_K_M` (built and tested with it) |
| `openai` | `OPENAI_API_KEY` (offered only when set), `OPENAI_MODEL`, `OPENAI_BASE_URL` | `gpt-5` |
| `claude` | `ANTHROPIC_API_KEY` (offered only when set), `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT` | `claude-opus-5-5`, Anthropic SDK, server-side refusal fallbacks on |

`LLM_PRESET` picks the starting preset.

## Demo shift and grading
`sre/demo.py` runs fault scenarios (`sre/scenarios.json`) on a timer when a flag backend is configured: `DEMO_FLAGS=file` with the flagd JSON at `DEMO_FLAG_FILE` (`/flags/demo.flagd.json`), or `DEMO_FLAGS=flagd-ui` on k8s (the OTel demo's flagd-ui API at `DEMO_FLAGD_UI_URL`=`http://flagd:4000`; the Helm chart copies the `flagd-config` ConfigMap into flagd once at start, so patching the ConfigMap does nothing). `DEMO=1` starts the shift at boot.
Knobs: `DEMO_SCRIPT` (fixed order, ends with the script), `DEMO_SEED`, `DEMO_SPEED` (divides durations and gaps; pair with the fast detector profile), `DEMO_QUIET_EVERY` (4), `DEMO_GAP_SECONDS` (60,120), `DEMO_FIRST_GAP_SECONDS` (240, baseline time), `DEMO_ANNOUNCE` (0: the agent finds problems from telemetry alone; 1 also publishes each flip as a `flag` change marker), `DEMO_REPORT_FILE`.
Controls: `POST /demo/start|pause|stop|reset`, `POST /demo/trigger {"id": ...}`, `GET /demo/status` (presenter view, includes what is injected). All flags are reset on start, stop and SIGTERM.
`sre/grade.py` scores investigations against the injected faults (`correct`, `partial`, `wrong`, `false-positive`, `no-answer`, plus missed faults): `GET /demo/grades`, `GET /demo/report` (markdown, also written when a shift ends). The agent's prompts and tools never see scenarios or expected answers.

## Fast iteration: capture once, replay in seconds
Live faults are slow (a fault needs minutes of real traffic to show, then minutes to age out), so tuning runs on recordings:

1. **Capture** (live, once per shop/instrumentation change, ~90 min for all scenarios): run a shift with `DEMO_SCRIPT=all` and
   `SRE_RECORD=/tmp/capture.jsonl`. Every detect poll appends one line: time, active scenario and its expected answer, and the
   TinyOlly responses (spans and logs as deltas, plus catalog, events, service map). Copy it out (`docker cp` / `kubectl cp`),
   `gzip` it into `recordings/` (git-ignored; ~100-200 MB raw for a full capture).
2. **Replay detection** (seconds): `python -m sre.replay recordings/k8s-all.jsonl.gz [--timeline] [--set DETECT_ERROR_PCT_MIN=3 ...]`
   runs the real detectors and incident logic on the recorded clock and prints the graded shift report. Sweep a setting with a shell loop.
3. **Replay investigations** (10-60 s per incident on the local model): add `--model`. The model gets the recorded evidence and
   replay versions of the TinyOlly tools (`what_changed`, `search_spans`, `query_logs`, `get_trace`, `get_edge`, `compare_windows`, `list_services`).
4. **Live shift** only to confirm, and for the demo itself.

## Run
```bash
k8s/06-rebuild+deploy-sre.sh [--demo [--realistic]] [--agents]   # SRE_LLM_URL, SRE_MODEL override the model; --demo uses flagd-ui, no RBAC needed; --agents adds the AI-agents add-on
```
`--demo` uses the **quick** profile by default (values in `k8s/06-rebuild+deploy-sre.sh`): `DEMO_PROFILE=quick` (each scenario's `quick` block: stronger variant, 75-90 s fault, 30 s cooldown), 5 s polls, `DETECT_RECENT_STATS=1` (rate and p95 from the last `DETECT_RECENT_SECONDS`=30 of spans), a detector cutoff when each fault ends, `CHANGE_NOTES=0`. The shift keeps the size profile's load. `--realistic` keeps the demo's strengths and the default timing.

## Standalone edition
This directory is self-contained (own Dockerfile, requirements, tests; build context is this directory; stdlib + httpx, plus the Anthropic SDK for the Claude preset; no tinyolly imports). To split it out: `git subtree split` / copy the directory, done.
Only `sre/backends/` knows a product. A new backend subclasses `sre.backend.Backend` (`detect`, `evidence`, `review_evidence`, `changes`, `publish`, `duties`, plus `mcp_url`/`mcp_allow`) and is registered in `sre/backends/__init__.py`; select it with `SRE_BACKEND`.

## Tests
`python -m venv .venv && .venv/bin/pip install -r requirements-test.txt && .venv/bin/python -m pytest tests`
