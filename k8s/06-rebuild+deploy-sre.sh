#!/usr/bin/env bash
# Deploy the TinyOlly AI SRE Agent (image from Docker Hub) and print how to open the console.
#   --build builds the image from this checkout instead (also done when Docker Hub has none).
#   ./06-rebuild+deploy-sre.sh           agent only
#   ./06-rebuild+deploy-sre.sh --demo [--realistic]   agent + demo shift (flags via the flagd-ui API; needs k8s-otel-demo).
#                                        Default timing quick (~2 min per scenario); --realistic: the demo's own fault strengths and timing
#   SRE_LLM_URL / SRE_MODEL / SRE_PRESET override the model defaults in tinyolly-sre.yaml (pass them on every run).
#                                        DEMO=0 waits for POST /demo/start; DEMO_SCRIPT=payment-degraded,quiet,... for a rehearsed run
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set -euo pipefail
DEMO_ON=""; QUICK=1; BUILD=""
for a in "$@"; do case "$a" in --demo) DEMO_ON=1;; --build) BUILD=1;; --realistic) QUICK="";; --quick) QUICK=1;;
  -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "unknown option $a (see --help)" >&2; exit 2;; esac; done
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# The cluster pulls the image itself (imagePullPolicy IfNotPresent, like the core services).
if [ -n "$BUILD" ] || ! docker manifest inspect tinyolly/sre:latest >/dev/null 2>&1; then
  docker build -t tinyolly/sre:latest docker/apps/tinyolly-sre
  kind load docker-image tinyolly/sre:latest --name "${KIND_CLUSTER:-tinyolly}"
fi
kubectl apply -f k8s/tinyolly-sre.yaml                        # resets the model settings to the manifest's defaults
MODEL_ENV=(${SRE_LLM_URL:+"LLM_URL=$SRE_LLM_URL"} ${SRE_MODEL:+"MODEL=$SRE_MODEL"} ${SRE_PRESET:+"LLM_PRESET=$SRE_PRESET"})
[ "${#MODEL_ENV[@]}" -eq 0 ] || kubectl set env deploy/tinyolly-sre "${MODEL_ENV[@]}"
QUICK_ENV=(DEMO_PROFILE=quick DEMO_GAP_SECONDS=20,30 DETECT_SECONDS=5 WARMUP_SECONDS=20 BASELINE_POLLS=6 DETECT_CONFIRM_POLLS=2
  INCIDENT_SETTLE_SECONDS=10 INCIDENT_CLEAR_POLLS=3 DETECT_RECENT_SECONDS=30 DETECT_WINDOW_SECONDS=60 DETECT_RECENT_STATS=1
  DETECT_HOLD_MAX_POLLS=36 CHANGE_NOTES=0)
if [ -n "$DEMO_ON" ]; then
  # Flags go through the OTel demo's flagd-ui API (flagd:4000), which edits the file flagd serves; no RBAC needed.
  kubectl get svc flagd >/dev/null || { echo "flagd service not found; deploy k8s-otel-demo first." >&2; exit 1; }
  # Start the shift only once the shop is up: on a fresh cluster the demo's images can still be pulling.
  echo "Waiting for the OpenTelemetry Demo deployments to be available (up to ${DEMO_WAIT:-300s})..."
  kubectl wait --for=condition=Available deploy -l app.kubernetes.io/part-of=opentelemetry-demo --timeout="${DEMO_WAIT:-300s}" >/dev/null || {
    echo "The OpenTelemetry Demo is not ready yet (kubectl get pods); rerun this script when it is." >&2; exit 1; }
  kubectl set env deploy/tinyolly-sre DEMO_FLAGS=flagd-ui DEMO_FLAGD_UI_URL="${DEMO_FLAGD_UI_URL:-http://flagd:4000}" DEMO="${DEMO:-1}" \
    DEMO_SCRIPT="${DEMO_SCRIPT:-}" DEMO_SEED="${DEMO_SEED:-}" DEMO_SPEED="${DEMO_SPEED:-1}" DEMO_ANNOUNCE="${DEMO_ANNOUNCE:-0}" SRE_RECORD="${SRE_RECORD:-}"
  if [ -n "$QUICK" ]; then         # default: problems show in seconds, ~2 min per scenario
    kubectl set env deploy/tinyolly-sre "${QUICK_ENV[@]}" DEMO_FIRST_GAP_SECONDS="${DEMO_FIRST_GAP_SECONDS:-60}"
  else                             # --realistic: the demo's own fault strengths, default detector timing
    kubectl set env deploy/tinyolly-sre $(printf '%s- ' "${QUICK_ENV[@]%%=*}") DEMO_PROFILE=realistic DEMO_FIRST_GAP_SECONDS="${DEMO_FIRST_GAP_SECONDS:-240}"
  fi
  source scripts/lib/size.sh     # the shift keeps the profile's load
  kubectl set env deploy/load-generator LOCUST_USERS="${LOCUST_USERS:-$LOAD_USERS}" LOCUST_BROWSER_TRAFFIC_ENABLED="$BROWSER_TRAFFIC"
fi
kubectl rollout restart deploy/tinyolly-sre
kubectl rollout status deploy/tinyolly-sre --timeout=300s   # a first pull takes a while
echo "Console: kubectl port-forward deploy/tinyolly-sre 7173:8080  ->  http://localhost:7173"
