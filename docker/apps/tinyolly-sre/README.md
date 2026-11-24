# tinyolly-sre

Generic AI SRE agent. Watches telemetry, groups failures into incidents, investigates each **once** with a model plus read-only MCP tools, then checks recovery when the signals clear.

## How it works
**Detectors** (no model call, every `DETECT_SECONDS`=30; pick with `DETECTORS`). Each signal names a service, and signals on one service join one incident.

| Detector | Fires when |
|---|---|
| `errors` | >= 10 failing spans of one service in 2 min |
| `error-rate` | service error % >= 5 and 3x its learned normal |
| `latency` | p95 >= 3x its learned normal (and +100 ms) |
| `traffic` | request rate < 20% of normal |
| `vanished` | a service that was reporting stops |
| `logs` | >= 10 error/fatal logs of one service in 2 min |
| `mesh` | new denied (403) or plaintext (non-mTLS) edge (Istio) |
| `platform` | TinyOlly's store >= 90% of its cap, or metric series dropped |

"Learned normal" is a per-service moving average; it needs `BASELINE_POLLS` (6) polls, a shift must hold `DETECT_CONFIRM_POLLS` (2) polls, and a problem is never learned as normal. `DETECT_IGNORE` (load-generator) is skipped.

**Incidents:** settle `INCIDENT_SETTLE_SECONDS` (30), investigate once, then a **runbook** note (up to 3 next steps). After `INCIDENT_CLEAR_POLLS` (2) quiet polls it resolves and runs a recovery check (`Recovered: yes|no`, last minute, no tools).

**Notes with a model, own budget** (`REVIEW_MAX_PER_HOUR` 30; skipped during warm-up, while an incident is open, or while the model is busy):
- **Change-risk note** and **post-change check** (`CHANGE_CHECK_SECONDS` 150) for every new change marker (`CHANGE_NOTES`=1): blast radius from the service map, what to watch, then whether anything regressed.
- **Reviews** every `REVIEW_EVERY_SECONDS` (300), rotating: `shift-note`, `instrumentation-gaps` (services without logs or trace ids), `platform-health`, `mesh-posture`.
- **Digest** of the agent's own findings every 30 min (`DIGEST_EVERY_SECONDS`).
- Each note starts with `VERDICT: ok|watch|act` and is published as an `ai-review` marker.

**Guardrails:** `MAX_TOOL_CALLS` 6, `DEADLINE_SECONDS` 120, `MAX_INVESTIGATIONS_PER_HOUR` 12, tool allowlist, `WARMUP_SECONDS` 60. Cited trace ids and services are kept only if they appeared in evidence or tool results.

**Output:** console at `:7173` (live log, click a line for prompts, replies and tool calls, ask box), and `ai-finding` / `ai-review` change markers written back to TinyOlly (`POST /api/events`). `POST /investigate {"alert": "..."}`, `POST /ask {"question": "..."}`, `GET /events`, `GET /healthz`.

## Run
```bash
cd docker && ./05-start-sre.sh      # Docker: needs the core stack up and Ollama on the host (SRE_MODEL, SRE_LLM_URL)
k8s/06-rebuild+deploy-sre.sh        # kind
```
Any OpenAI-compatible model: `LLM_URL`, `MODEL`, `LLM_API_KEY`.

## Standalone edition
This directory is self-contained (own Dockerfile, requirements, tests; build context is this directory; stdlib + httpx only; no tinyolly imports). To split it out: `git subtree split` / copy the directory, done.
Only `sre/backends/` knows a product. A new backend subclasses `sre.backend.Backend` (`detect`, `evidence`, `review_evidence`, `changes`, `publish`, `duties`, plus `mcp_url`/`mcp_allow`) and is registered in `sre/backends/__init__.py`; select it with `SRE_BACKEND`.

## Tests
`python -m venv .venv && .venv/bin/pip install -r requirements-test.txt && .venv/bin/python -m pytest tests`
