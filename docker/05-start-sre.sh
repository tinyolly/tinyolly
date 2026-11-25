#!/usr/bin/env bash
# Start the opt-in TinyOlly AI SRE Agent next to a running core stack. Model: SRE_MODEL (default qwen3.8:27b-mtp-q4_K_M) at SRE_LLM_URL (default: the local Ollama box); OPENAI_API_KEY / ANTHROPIC_API_KEY add cloud presets.
#   ./05-start-sre.sh           agent only
#   ./05-start-sre.sh --demo [--realistic]   agent + demo shift driver. Default profile: quick (docker-compose-sre-quick.yml,
#                                            stronger faults, ~2 min per scenario, shop load raised to DEMO_LOAD_USERS=20).
#                                            --realistic: the demo's own fault strengths and load, 30 s polls, ~10 min per scenario. (needs the OTel demo cloned: ../docker-otel-demo/01-start-otel-demo.sh).
#                               DEMO=0 mounts the flags but waits for POST /demo/start; DEMO_SCRIPT=payment-degraded,quiet,... for a rehearsed run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
FILES=(-f docker-compose-tinyolly-core-local.yml)
DEMO=""; QUICK=1
for a in "$@"; do case "$a" in --demo) DEMO=1;; --realistic) QUICK="";; --quick|--fast) QUICK=1;; *) echo "unknown option $a" >&2; exit 2;; esac; done
if [ -n "$DEMO" ]; then
  [ -f ../docker-otel-demo/.demo/src/flagd/demo.flagd.json ] || { echo "OTel demo not cloned; run ../docker-otel-demo/01-start-otel-demo.sh first." >&2; exit 1; }
  FILES+=(-f docker-compose-sre-demo.yml)
fi
if [ -n "$DEMO" ] && [ -n "$QUICK" ]; then
  FILES+=(-f docker-compose-sre-quick.yml)
  ../docker-otel-demo/04-set-load.sh "${DEMO_LOAD_USERS:-20}"
elif [ -n "$DEMO" ]; then
  ../docker-otel-demo/04-set-load.sh "${LOCUST_USERS:-3}"          # realistic: the demo's own load
fi
docker compose "${FILES[@]}" --profile sre up -d --build tinyolly-sre
echo "TinyOlly AI SRE Agent console: http://localhost:7173"
[ -n "$DEMO" ] && echo "Demo driver: curl -s localhost:7173/demo/status | python3 -m json.tool"
exit 0
