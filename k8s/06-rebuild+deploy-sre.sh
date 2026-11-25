#!/usr/bin/env bash
# Build the TinyOlly AI SRE Agent image, load it into kind, deploy it, and print how to open the console.
#   ./06-rebuild+deploy-sre.sh           agent only
#   ./06-rebuild+deploy-sre.sh --demo [--realistic]   agent + demo shift (flags via the flagd-ui API; needs k8s-otel-demo).
#                                        Default profile quick (~2 min per scenario, load raised to DEMO_LOAD_USERS=20); --realistic: demo defaults
#                                        DEMO=0 waits for POST /demo/start; DEMO_SCRIPT=payment-degraded,quiet,... for a rehearsed run
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker build -t tinyolly/sre:latest docker/apps/tinyolly-sre
kind load docker-image tinyolly/sre:latest --name "${KIND_CLUSTER:-tinyolly}"
kubectl apply -f k8s/tinyolly-sre.yaml
DEMO_ON=""; QUICK=1
for a in "$@"; do case "$a" in --demo) DEMO_ON=1;; --realistic) QUICK="";; --quick) QUICK=1;; *) echo "unknown option $a" >&2; exit 2;; esac; done
QUICK_ENV=(DEMO_PROFILE=quick DEMO_GAP_SECONDS=20,30 DETECT_SECONDS=5 WARMUP_SECONDS=20 BASELINE_POLLS=6 DETECT_CONFIRM_POLLS=2
  INCIDENT_SETTLE_SECONDS=10 INCIDENT_CLEAR_POLLS=3 DETECT_RECENT_SECONDS=30 DETECT_WINDOW_SECONDS=60 DETECT_RECENT_STATS=1
  DETECT_HOLD_MAX_POLLS=36 CHANGE_NOTES=0)                       # same as docker/docker-compose-sre-quick.yml
if [ -n "$DEMO_ON" ]; then
  # Flags go through the OTel demo's flagd-ui API (flagd:4000), which edits the file flagd serves; no RBAC needed.
  kubectl get svc flagd >/dev/null || { echo "flagd service not found; deploy k8s-otel-demo first." >&2; exit 1; }
  kubectl set env deploy/tinyolly-sre DEMO_FLAGS=flagd-ui DEMO_FLAGD_UI_URL="${DEMO_FLAGD_UI_URL:-http://flagd:4000}" DEMO="${DEMO:-1}" \
    DEMO_SCRIPT="${DEMO_SCRIPT:-}" DEMO_SEED="${DEMO_SEED:-}" DEMO_SPEED="${DEMO_SPEED:-1}" DEMO_ANNOUNCE="${DEMO_ANNOUNCE:-1}" SRE_RECORD="${SRE_RECORD:-}"
  if [ -n "$QUICK" ]; then         # default: problems show in seconds, ~2 min per scenario; shop load raised to DEMO_LOAD_USERS
    kubectl set env deploy/tinyolly-sre "${QUICK_ENV[@]}" DEMO_FIRST_GAP_SECONDS="${DEMO_FIRST_GAP_SECONDS:-60}"
    kubectl set env deploy/load-generator LOCUST_USERS="${DEMO_LOAD_USERS:-20}"
  else                             # --realistic: the demo's own fault strengths and load, default detector timing
    kubectl set env deploy/tinyolly-sre $(printf '%s- ' "${QUICK_ENV[@]%%=*}") DEMO_PROFILE=realistic DEMO_FIRST_GAP_SECONDS="${DEMO_FIRST_GAP_SECONDS:-240}"
    kubectl set env deploy/load-generator LOCUST_USERS="${LOCUST_USERS:-3}"
  fi
fi
kubectl rollout restart deploy/tinyolly-sre
kubectl rollout status deploy/tinyolly-sre --timeout=90s
echo "Console: kubectl port-forward deploy/tinyolly-sre 7173:8080  ->  http://localhost:7173"
