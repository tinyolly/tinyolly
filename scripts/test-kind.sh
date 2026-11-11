#!/usr/bin/env bash
# Local-only smoke test of the Kubernetes path on kind (inside the Colima VM).
#   ./scripts/test-kind.sh          core + collector (k8s/) and core-only (k8s-core-only/)
#   ./scripts/test-kind.sh --demo   also builds and deploys k8s-demo
# Stops the compose stack (it owns host ports 5005/4317), creates a throwaway kind cluster, loads the LOCAL
# images (build them first: docker/01-start-core-local.sh), checks the UI and ingest, then deletes the
# cluster and restarts the compose stack if it was running.
set -uo pipefail
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${KIND_CLUSTER:-tinyolly}"
COMPOSE=(docker compose -f "$ROOT/docker/docker-compose-tinyolly-core-local.yml")
DEMO=0; [ "${1:-}" = "--demo" ] && DEMO=1
FAILS=0
ok()   { echo "  ✓ $*"; }
bad()  { echo "  ✗ $*"; FAILS=$((FAILS+1)); }
check(){ local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }

for c in kind kubectl docker; do command -v $c >/dev/null || { echo "missing: $c (brew install $c)"; exit 2; }; done
docker info >/dev/null 2>&1 || { echo "Colima VM '$DOCKER_CONTEXT' not running: scripts/colima-up.sh"; exit 2; }
for i in ui otlp-receiver opamp-server otel-supervisor; do
  docker image inspect "tinyolly/$i:latest" >/dev/null 2>&1 || { echo "missing local image tinyolly/$i:latest: build with docker/01-start-core-local.sh"; exit 2; }
done

WAS_UP=0; [ -n "$("${COMPOSE[@]}" ps -q 2>/dev/null)" ] && WAS_UP=1
cleanup() {
  echo "== cleanup"
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1
  [ "$WAS_UP" = 1 ] && "${COMPOSE[@]}" start >/dev/null 2>&1 && echo "  compose stack restarted"
  return 0
}
trap cleanup EXIT

[ "$WAS_UP" = 1 ] && { echo "== stopping compose stack"; "${COMPOSE[@]}" stop >/dev/null 2>&1; }
echo "== kind cluster"
"$ROOT/scripts/kind-up.sh" >/dev/null 2>&1 && ok "cluster up" || { bad "kind-up.sh failed"; exit 1; }
for i in ui otlp-receiver opamp-server otel-supervisor; do kind load docker-image "tinyolly/${i}:latest" --name "$CLUSTER" >/dev/null 2>&1; done

wait_ready() { kubectl wait --for=condition=available deploy --all --timeout=180s >/dev/null 2>&1; }
ui_ok()      { curl -sf -o /dev/null localhost:5005/; }
has_svc()    { curl -sf localhost:5005/api/service-catalog | grep -q "\"name\":\"$1\""; }
retry()      { for _ in $(seq 1 30); do "$@" && return 0; sleep 3; done; return 1; }

echo "== k8s-core-only"
( cd "$ROOT/k8s-core-only" && ./01-deploy.sh >/dev/null 2>&1 ) && ok "applied" || bad "apply failed"
check "deployments available" wait_ready
check "UI answers on :5005" retry ui_ok
check "UI self-telemetry ingested via gRPC receiver" retry has_svc tinyolly-ui
kubectl delete -f "$ROOT/k8s-core-only/" --ignore-not-found >/dev/null 2>&1

echo "== k8s (core + collector)"
( cd "$ROOT/k8s" && ./02-deploy-tinyolly.sh >/dev/null 2>&1 ) && ok "applied" || bad "apply failed"
check "deployments available" wait_ready
check "UI answers on :5005" retry ui_ok
opamp_agent() { curl -sf localhost:5005/api/opamp/status | python3 -c "import sys,json;sys.exit(0 if json.load(sys.stdin)['agent_count']>=1 else 1)"; }
check "collector registered with OpAMP" retry opamp_agent
send_otlp() { curl -sf -X POST localhost:4318/v1/traces -H 'content-type: application/json' -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"kind-smoke"}}]},"scopeSpans":[{"spans":[{"traceId":"0af7651916cd43dd8448eb211c80319c","spanId":"b7ad6b7169203331","name":"smoke","kind":2,"startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000000500000000"}]}]}]}'; }
check "OTLP/HTTP through collector reaches TinyOlly" retry send_otlp
check "ingested trace visible in catalog" retry has_svc kind-smoke

if [ "$DEMO" = 1 ]; then
  echo "== k8s-demo"
  ( cd "$ROOT/k8s-demo" && printf 'y\n' | ./02-deploy.sh >/dev/null 2>&1 ) && ok "applied" || bad "apply failed"
  check "demo deployments available" wait_ready
  check "demo-frontend answers on :5001" retry curl -sf -o /dev/null localhost:5001/
  check "demo traffic ingested" retry has_svc demo-frontend
  git -C "$ROOT" diff --quiet -- "k8s-demo/demo-*.yaml" || bad "k8s-demo manifests left modified"
fi

echo; [ $FAILS -eq 0 ] && echo "kind smoke test: PASS" || echo "kind smoke test: $FAILS FAILED"
exit $((FAILS>0))
