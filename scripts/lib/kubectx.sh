#!/usr/bin/env bash
# Safety guard for scripts that create/delete Kubernetes resources.
# These scripts delete Deployments, Services, ConfigMaps and the tinyolly-db PVC in whatever kubectl context is current,
# so refuse to run unless it is the local kind cluster (kind-${KIND_CLUSTER:-tinyolly}).
# Override deliberately with TINYOLLY_ALLOW_ANY_CONTEXT=1 (e.g. to deploy to another cluster you know is safe).
require_kind_context() {
  local want="kind-${KIND_CLUSTER:-tinyolly}"
  local cur
  cur=$(kubectl config current-context 2>/dev/null || true)
  if [ "$cur" = "$want" ] || [ "${TINYOLLY_ALLOW_ANY_CONTEXT:-0}" = "1" ]; then
    return 0
  fi
  {
    echo "ERROR: kubectl context is '${cur:-<none>}', but this script only runs against the local kind cluster '$want'."
    echo "       Start it with ./scripts/kind-up.sh (or: kubectl config use-context $want)."
    echo "       To run against another cluster on purpose: TINYOLLY_ALLOW_ANY_CONTEXT=1 $0"
  } >&2
  return 1
}
