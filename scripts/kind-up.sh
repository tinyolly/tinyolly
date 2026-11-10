#!/usr/bin/env bash
# Create the 'tinyolly' kind cluster on Colima (idempotent).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/lib/preflight.sh"; tinyolly_preflight
if kind get clusters 2>/dev/null | grep -qx tinyolly; then
  echo "kind cluster 'tinyolly' already exists."
else
  kind create cluster --name tinyolly --config "$DIR/kind-config.yaml"
fi
kubectl config use-context kind-tinyolly >/dev/null
kubectl get nodes
