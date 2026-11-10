#!/usr/bin/env bash
# Create the 'tinyolly' kind cluster on Colima (idempotent).
set -euo pipefail
CLUSTER="${KIND_CLUSTER:-tinyolly}"
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/lib/preflight.sh"; tinyolly_preflight
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "kind cluster '$CLUSTER' already exists."
else
  kind create cluster --name "$CLUSTER" --config "$DIR/kind-config.yaml"
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null
kubectl get nodes
