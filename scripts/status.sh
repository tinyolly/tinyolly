#!/usr/bin/env bash
# One screen: what is running, what is deployed, what uses space, and how to clean each thing up. Read-only.
#   scripts/status.sh            # everything
#   scripts/status.sh --short    # skip the per-namespace pod table and disk details
# Covers the Colima VMs, the kind cluster and its Helm releases, TinyOlly, the demos (OpenTelemetry Demo, Istio
# ambient demo) and TinyOlly's endpoints.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORT=0; [ "${1:-}" = "--short" ] && SHORT=1
KCTX="kind-${KIND_CLUSTER:-tinyolly}"
B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; N=$'\033[0m'
hdr() { printf '\n%s== %s ==%s\n' "$B" "$1" "$N"; }
ok()  { printf '  %s●%s %s\n' "$G" "$N" "$1"; }
off() { printf '  %s○%s %s\n' "$D" "$N" "$1"; }
bad() { printf '  %s✖%s %s\n' "$R" "$N" "$1"; }
hint() { printf '      %scleanup: %s%s\n' "$D" "$1" "$N"; }

docker_up() { docker --context "$1" info >/dev/null 2>&1; }
kube_up()   { kubectl --context "$KCTX" get ns >/dev/null 2>&1; }

hdr "Colima VMs"
colima list 2>/dev/null | sed 's/^/  /' || echo "  colima not installed"
printf '  %sactive docker context: %s   kubectl context: %s%s\n' "$D" "$(docker context show 2>/dev/null)" "$(kubectl config current-context 2>/dev/null)" "$N"

hdr "kind cluster ($KCTX)"
if kube_up; then
  ok "cluster reachable"
  helm --kube-context "$KCTX" list -A -o json 2>/dev/null | jq -r '.[] | "      helm: \(.name) (\(.namespace)) \(.status) \(.chart)"'
  kubectl --context "$KCTX" get pods -A --no-headers 2>/dev/null | awk '{ns=$1; n[ns]++; if ($4!="Running" && $4!="Completed") b[ns]++}
    END{for (ns in n) printf "      ns %-20s %3d pod(s)%s\n", ns, n[ns], (b[ns]? "  ["b[ns]" not Running]":"")}' | sort
  if [ "$SHORT" = 0 ]; then
    kubectl --context "$KCTX" describe node 2>/dev/null | awk '/Allocated resources/{f=1} f&&/memory/{print "      node memory: requests " $2 " " $3 ", limits " $4 " " $5; exit}'
  fi
else
  off "not reachable (VM stopped or cluster not created: scripts/kind-up.sh)"
fi

hdr "What is deployed (and how to remove it)"
# TinyOlly on kind
if kube_up && kubectl --context "$KCTX" get deploy tinyolly-ui >/dev/null 2>&1; then
  ready=$(kubectl --context "$KCTX" get deploy tinyolly-ui -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  [ "${ready:-0}" -ge 1 ] && ok "TinyOlly on kind (UI :5005, MCP :8765)" || bad "TinyOlly on kind: UI not ready"
  hint "k8s/03-cleanup.sh   (kind cluster itself: kind delete cluster --name ${KIND_CLUSTER:-tinyolly})"
else off "TinyOlly on kind"; fi
# OpenTelemetry Demo on kind
if kube_up; then
  rel=$(helm --kube-context "$KCTX" list -A -o json 2>/dev/null | jq -r '.[] | select(.name=="my-otel-demo") | .status')
  if [ -n "$rel" ]; then
    n=$(kubectl --context "$KCTX" get deploy -l app.kubernetes.io/part-of=opentelemetry-demo --no-headers 2>/dev/null | wc -l | tr -d ' ')
    ok "OpenTelemetry Demo on kind (helm my-otel-demo: $rel, $n deployments)"
    hint "k8s-otel-demo/02-cleanup-otel-demo-helm.sh"
  else off "OpenTelemetry Demo on kind"; fi
  # Istio ambient demo
  if kubectl --context "$KCTX" get ns istio-system >/dev/null 2>&1 || kubectl --context "$KCTX" get ns boutique >/dev/null 2>&1; then
    wp=$(kubectl --context "$KCTX" -n boutique get gateway waypoint -o name 2>/dev/null | head -1)
    ok "Istio ambient demo on kind (shop in 'boutique'${wp:+, waypoint on})"
    hint "../istio-ambient-demo/04-cleanup.sh   (reset scenarios only: ./03-scenario.sh reset)"
  else off "Istio ambient demo"; fi
fi

hdr "TinyOlly endpoints"
check() { # name url-base mcp-port
  local code n
  code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$2/health" 2>/dev/null)
  if [ "$code" = "200" ]; then
    n=$(curl -s -m 5 "$2/api/service-catalog" 2>/dev/null | jq 'length' 2>/dev/null)
    ok "$1 UI $2 — ${n:-?} services in the catalog"
  else off "$1 UI $2 (not answering)"; fi
}
check "kind  " http://localhost:5005
for p in 8765:kind; do
  code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${p%%:*}/mcp" -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"status","version":"1"}}}' 2>/dev/null)
  [ "$code" = "200" ] && ok "MCP ${p##*:}  http://127.0.0.1:${p%%:*}/mcp" || off "MCP ${p##*:}  :${p%%:*} (not answering)"
done

if [ "$SHORT" = 0 ]; then
  hdr "Disk"
  printf '  free on /: %s   colima home: %s\n' "$(df -h / | awk 'NR==2{print $4}')" "$(du -sh "${COLIMA_HOME:-$HOME/.colima}" 2>/dev/null | cut -f1)"
  printf '  %sreclaim build cache: docker --context colima-tinyolly builder prune -af%s\n' "$D" "$N"
fi
printf '\n'
