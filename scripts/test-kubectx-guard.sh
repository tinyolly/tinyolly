#!/usr/bin/env bash
# Regression test for scripts/lib/kubectx.sh: cluster-mutating scripts must refuse to run outside the kind cluster.
# Uses a fake `kubectl` (and `helm`) on PATH that records every call; no cluster needed.
set -uo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d -p "$PWD" .kubectx-test.XXXXXX)      # inside the repo: Colima/containers cannot see /tmp
trap 'rm -rf "$TMP"' EXIT
LOG="$TMP/calls.log"
cat > "$TMP/kubectl" <<EOS
#!/usr/bin/env bash
echo "kubectl \$*" >> "$LOG"
if [ "\$1 \$2" = "config current-context" ]; then echo "\${FAKE_CONTEXT:-}"; fi
exit 0
EOS
printf '#!/usr/bin/env bash\necho "helm $*" >> "%s"\nexit 0\n' "$LOG" > "$TMP/helm"
chmod +x "$TMP/kubectl" "$TMP/helm"

fail=0
check() { if [ "$2" = "ok" ]; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }

# Every script that mutates a cluster must be guarded (so a new unguarded script fails this test).
UNGUARDED=$(grep -lE '(kubectl[[:space:]]+(apply|delete|create|rollout|scale|patch|replace)|helm[[:space:]]+(upgrade|install|uninstall))' k8s/*.sh k8s-core-only/*.sh k8s-demo/*.sh k8s-demo-ebpf/*.sh k8s-otel-demo/*.sh k8s-ai-agent-demo/*.sh 2>/dev/null | xargs grep -L 'kubectx.sh' 2>/dev/null)
if [ -n "$UNGUARDED" ]; then echo "FAIL  mutating scripts without the context guard:"; echo "$UNGUARDED" | sed 's/^/        /'; fail=1; else echo "ok    every cluster-mutating script is guarded"; fi

SCRIPTS=$(grep -l 'kubectx.sh' k8s/*.sh k8s-core-only/*.sh k8s-demo/*.sh k8s-demo-ebpf/*.sh k8s-otel-demo/*.sh k8s-ai-agent-demo/*.sh 2>/dev/null)
[ -n "$SCRIPTS" ] || { echo "FAIL  no guarded scripts found"; exit 1; }

for s in $SCRIPTS; do
  : > "$LOG"
  FAKE_CONTEXT="prod-eks" PATH="$TMP:$PATH" bash "$s" </dev/null >/dev/null 2>"$TMP/err"
  rc=$?
  others=$(grep -v 'config current-context' "$LOG" | wc -l | tr -d ' ')
  if [ "$rc" -ne 0 ] && [ "$others" = "0" ] && grep -q "only runs against the local kind cluster" "$TMP/err"; then
    check "refuses prod-eks:        $s" ok
  else
    check "refuses prod-eks:        $s (rc=$rc, other kubectl/helm calls=$others)" bad
  fi
done

# The guard function itself
source scripts/lib/kubectx.sh
export PATH="$TMP:$PATH"
FAKE_CONTEXT=kind-tinyolly require_kind_context 2>/dev/null && check "allows kind-tinyolly" ok || check "allows kind-tinyolly" bad
FAKE_CONTEXT=docker-desktop require_kind_context 2>/dev/null && check "refuses docker-desktop" bad || check "refuses docker-desktop" ok
FAKE_CONTEXT="" require_kind_context 2>/dev/null && check "refuses empty context" bad || check "refuses empty context" ok
FAKE_CONTEXT=kind-foo KIND_CLUSTER=foo require_kind_context 2>/dev/null && check "honours KIND_CLUSTER" ok || check "honours KIND_CLUSTER" bad
FAKE_CONTEXT=kind-tinyolly KIND_CLUSTER=foo require_kind_context 2>/dev/null && check "KIND_CLUSTER mismatch refused" bad || check "KIND_CLUSTER mismatch refused" ok
FAKE_CONTEXT=prod TINYOLLY_ALLOW_ANY_CONTEXT=1 require_kind_context 2>/dev/null && check "explicit override works" ok || check "explicit override works" bad
exit $fail
