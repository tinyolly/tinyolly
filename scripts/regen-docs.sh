#!/usr/bin/env bash
# Regenerate every documentation image from the running kind stack (TinyOlly, the OpenTelemetry Demo, the AI SRE Agent),
# then check them. Refuses to run during an SRE demo shift (the OTel demo shots inject their own failure).
#   scripts/regen-docs.sh              # all of it; takes several minutes
#   scripts/regen-docs.sh --otel       # only the OpenTelemetry Demo shots
# Needs UI :5005 and MCP :8765 reachable. The agentgateway add-on's bots, if deployed, are paused and then restored.
# The mesh-* charts come from seeded data in a temporary second TinyOlly (namespace tinyolly-docshots), removed at the end.
# Not regenerated: ui-agent-map / mesh-agent-trace-path (agentgateway-demo) and the Istio shots (the Istio demo repo).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
K="kubectl --context kind-${KIND_CLUSTER:-tinyolly}"
PY="${PYTHON:-docker/apps/tinyolly-mcp/.venv/bin/python}"      # has Pillow and matplotlib
NS=tinyolly-docshots
PIDS=()
OTEL_ONLY=""; [ "${1:-}" != --otel ] || OTEL_ONLY=1
say() { printf '==> %s\n' "$*"; }

# ---- preconditions
$K exec deploy/tinyolly-sre -- python -c "
import json,sys,urllib.request as u
d=json.load(u.urlopen('http://localhost:8080/api/investigations'))['status'].get('demo') or {}
sys.exit(0 if d.get('state','stopped')=='stopped' else 1)" || { echo "an SRE demo shift is running: stop it first (POST /demo/stop on the agent)" >&2; exit 1; }
curl -sf -m 10 -o /dev/null http://localhost:5005/api/service-map || { echo "TinyOlly UI not reachable on :5005" >&2; exit 1; }

# ---- pause the add-on's traffic so it is not in the shots
BOTS=""
$K get ns agent-demo >/dev/null 2>&1 && BOTS=1
restore() {
  for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null || true; done
  $K delete ns $NS --ignore-not-found --wait=false >/dev/null 2>&1 || true
  if [ -n "$BOTS" ]; then
    say "restoring the agent bots"
    for b in giftbot budgetbot dealbot; do $K scale -n agent-demo "deploy/$b-stable-$b" --replicas=1 >/dev/null || true; done
    $K scale -n agent-demo deploy/agentgateway-metrics --replicas=1 >/dev/null || true
    $K scale -n kagent deploy/kagent-controller --replicas=1 >/dev/null || true
  fi
}
trap restore EXIT
if [ -n "$BOTS" ]; then
  say "pausing the agent bots"
  $K scale -n kagent deploy/kagent-controller --replicas=0 >/dev/null      # or it scales the bots back
  for b in giftbot budgetbot dealbot; do $K scale -n agent-demo "deploy/$b-stable-$b" --replicas=0 >/dev/null; done
  $K scale -n agent-demo deploy/agentgateway-metrics --replicas=0 >/dev/null
  say "waiting for them to leave the service map"
  for i in $(seq 1 60); do
    curl -s -m 30 http://localhost:5005/api/service-map | grep -qE 'giftbot|budgetbot|dealbot|agentgateway-proxy' || break
    [ "$i" -lt 60 ] || { echo "bots still on the map after 10 minutes" >&2; exit 1; }
    sleep 10
  done
fi

if [ -z "$OTEL_ONLY" ]; then
say "AI SRE Agent console"
if ! curl -sf -m 3 -o /dev/null http://localhost:7173/healthz; then
  $K port-forward deploy/tinyolly-sre 7173:8080 >/dev/null 2>&1 & PIDS+=($!); sleep 3
fi
node scripts/shoot-sre-console.mjs

say "UI tabs"
UI_ONLY=(); for n in logs metrics traces service-catalog service-map collector; do UI_ONLY+=(--only "ui-$n"); done
"$PY" scripts/make-doc-images.py "${UI_ONLY[@]}"

say "mesh charts (temporary TinyOlly with seeded data)"
$K create ns $NS >/dev/null
for f in k8s/otelcol-configs/config.yaml k8s/otelcol-configs/supervisor.yaml k8s/otelcol-configs/templates/templates.yaml \
         k8s/tinyolly-sqlite-pvc.yaml k8s/tinyolly-opamp-server.yaml k8s/otel-collector.yaml k8s/tinyolly-otlp-receiver.yaml k8s/tinyolly-ui.yaml k8s/tinyolly-mcp.yaml; do
  sed -e 's/^ *type: NodePort *$//' -e '/^ *nodePort:/d' "$f" | $K apply -n $NS -f - >/dev/null      # no fixed node ports twice
done
$K wait -n $NS --for=condition=Available deploy --all --timeout=240s >/dev/null
$K port-forward -n $NS svc/tinyolly-ui 15005:5002 >/dev/null 2>&1 & PIDS+=($!)
$K port-forward -n $NS svc/tinyolly-mcp 18765:8765 >/dev/null 2>&1 & PIDS+=($!)
$K port-forward -n $NS svc/otel-collector 14319:4318 >/dev/null 2>&1 & PIDS+=($!)
sleep 4
"$PY" scripts/make-doc-images.py --seed --ui http://localhost:15005 --mcp http://localhost:18765/mcp --otlp http://localhost:14319 \
  --only mesh-service-map --only mesh-map-diff --only mesh-trace-path

fi

say "OpenTelemetry Demo shots (injects paymentFailure, then turns it off)"
"$PY" scripts/make-otel-demo-images.py

if [ -z "$OTEL_ONLY" ]; then say "architecture diagram"; "$PY" scripts/make-architecture-diagram.py; fi
say "check"
"$PY" scripts/make-doc-images.py --check
