#!/bin/bash

# Safety: only operate on the local kind cluster (see scripts/lib/kubectx.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }

echo "========================================"
echo "TinyOlly Core Kubernetes Cleanup"
echo "========================================"

echo ""
echo "Checking for TinyOlly resources..."
echo "The following resources will be deleted:"
echo ""
kubectl get deployments,services,configmaps,pvc 2>/dev/null | grep -E "(tinyolly|otel-collector|tinyolly-db)" || echo "  (checking resources...)"
echo ""

read -p "Do you want to proceed with cleanup? [y/N]:" confirm
if [[ ! $confirm =~ ^[Yy]$ ]]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo ""
echo "Deleting TinyOlly resources..."

echo ""
echo "→ Deleting resources..."
kubectl delete -f tinyolly-ui.yaml --ignore-not-found
kubectl delete -f tinyolly-opamp-server.yaml --ignore-not-found
kubectl delete -f tinyolly-otlp-receiver.yaml --ignore-not-found
kubectl delete -f tinyolly-sqlite-pvc.yaml --ignore-not-found

echo ""
echo "→ Ensuring all configmaps are deleted..."
kubectl delete configmap otel-collector-config --ignore-not-found=true 2>/dev/null || true
kubectl delete configmap otelcol-templates --ignore-not-found=true 2>/dev/null || true

echo ""
echo "Waiting for pods to terminate..."
kubectl wait --for=delete pod -l app=tinyolly-otlp-receiver --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=tinyolly-opamp-server --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=tinyolly-ui --timeout=60s 2>/dev/null || true

echo ""
echo "Verifying cleanup..."
if [ -z "$(kubectl get pods -l app=tinyolly-ui -o name 2>/dev/null)" ]; then
    echo "✓ All TinyOlly resources have been deleted"
else
    echo "⚠ Some resources might still be terminating"
fi

echo ""
echo "========================================"
echo "Cleanup complete!"
echo "========================================"
