#!/usr/bin/env bash
# Build the AI SRE image, load it into kind, deploy it, and print how to open the console.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker build -t tinyolly/sre:latest docker/apps/tinyolly-sre
kind load docker-image tinyolly/sre:latest --name "${KIND_CLUSTER:-tinyolly}"
kubectl apply -f k8s/tinyolly-sre.yaml
kubectl rollout restart deploy/tinyolly-sre
kubectl rollout status deploy/tinyolly-sre --timeout=90s
echo "Console: kubectl port-forward deploy/tinyolly-sre 7173:8080  ->  http://localhost:7173"
