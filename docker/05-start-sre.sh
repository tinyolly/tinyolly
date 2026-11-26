#!/usr/bin/env bash
# Start the opt-in TinyOlly AI SRE Agent next to a running core stack. Model: SRE_MODEL (default qwen3.8:27b-mtp-q4_K_M) at SRE_LLM_URL (default: the local Ollama box); OPENAI_API_KEY / ANTHROPIC_API_KEY add cloud presets.
#   ./05-start-sre.sh           agent only
#   ./05-start-sre.sh --demo [--realistic]   agent + demo shift driver. Default profile: quick (docker-compose-sre-quick.yml,
#                                            stronger faults, ~2 min per scenario, shop load raised to DEMO_LOAD_USERS=20).
#                                            --realistic: the demo's own fault strengths and load, 30 s polls, ~10 min per scenario. (needs the OTel demo cloned: ../docker-otel-demo/01-start-otel-demo.sh).
#                               DEMO=0 mounts the flags but waits for POST /demo/start; DEMO_SCRIPT=payment-degraded,quiet,... for a rehearsed run.
set -euo pipefail
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")"
# Use the compose file the running core was started with, so the core containers are not re-created:
# 01-start-core.sh (Docker Hub images) or 01-start-core-local.sh (built from this checkout).
CORE=docker-compose-tinyolly-core.yml
case "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' tinyolly-ui 2>/dev/null)" in
  *core-local.yml*) CORE=docker-compose-tinyolly-core-local.yml;;
esac
FILES=(-f "$CORE")
DEMO=""; QUICK=1
for a in "$@"; do case "$a" in --demo) DEMO=1;; --realistic) QUICK="";; --quick|--fast) QUICK=1;;
  -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "unknown option $a (see --help)" >&2; exit 2;; esac; done
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
