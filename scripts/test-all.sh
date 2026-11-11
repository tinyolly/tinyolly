#!/usr/bin/env bash
# Run the local test suites (nothing runs in CI).
#   ./scripts/test-all.sh            fast suites: common, UI/API, receiver, MCP, frontend JS, Go, configs, kube guard
#   ./scripts/test-all.sh --stack    + e2e against the RUNNING stack (~8 min)
#   ./scripts/test-all.sh --kind     + kind smoke test (stops the compose stack temporarily)
set -uo pipefail
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
STACK=0; KIND=0
for a in "$@"; do case $a in --stack) STACK=1;; --kind) KIND=1;; *) echo "unknown: $a"; exit 2;; esac; done
FAILED=(); PY="${PYTHON:-$(command -v python3.13 || command -v python3.12 || command -v python3.14 || command -v python3)}"   # the apps pin Python 3.13 locks
run() { local name=$1; shift; echo; echo "━━ $name"; if "$@"; then echo "   ✓ $name"; else echo "   ✗ $name"; FAILED+=("$name"); fi; }
pytest_in() { # dir: ensure a venv with the app's deps exists, then pytest
  local dir=$1 venv="$ROOT/.venv-tests/$(basename "$1")"; shift
  [ -x "$venv/bin/python" ] || { "$PY" -m venv "$venv" || return 1; }
  ( cd "$dir" && "$venv/bin/pip" install -q "$@" && "$venv/bin/python" -m pytest tests -q )
}
run "tinyolly-common (pytest)"  pytest_in docker/apps/tinyolly-common -r "$ROOT/docker/apps/tinyolly-common/requirements-test.txt" "$ROOT/docker/apps/tinyolly-common"
run "tinyolly-ui (pytest)"      pytest_in docker/apps/tinyolly-ui -r "$ROOT/docker/apps/tinyolly-ui/requirements.txt" pytest pytest-asyncio httpx "$ROOT/docker/apps/tinyolly-common"
run "otlp-receiver (pytest)"    pytest_in docker/apps/tinyolly-otlp-receiver -r "$ROOT/docker/apps/tinyolly-otlp-receiver/requirements.txt" pytest pytest-asyncio httpx "$ROOT/docker/apps/tinyolly-common"
run "tinyolly-mcp (pytest)"     docker/apps/tinyolly-mcp/run-tests.sh
run "frontend JS (node --test)" node --test docker/apps/tinyolly-ui/tests-js/serviceMap.test.mjs
run "opamp-server (Go)"         scripts/test-go.sh
run "collector configs"         scripts/test-collector-configs.sh
run "kubectl-context guard"     scripts/test-kubectx-guard.sh
[ $STACK = 1 ] && run "e2e (running stack)" "$PY" scripts/e2e.py
[ $KIND = 1 ]  && run "kind smoke"          scripts/test-kind.sh
echo; if [ ${#FAILED[@]} -eq 0 ]; then echo "ALL PASSED"; else echo "FAILED: ${FAILED[*]}"; exit 1; fi
