#!/bin/bash

echo "========================================"
echo "TinyOlly Core Kubernetes Cleanup"
echo "========================================"

echo ""
echo "Checking for TinyOlly resources..."
echo "The following resources will be deleted:"
echo ""
kubectl get deployments,services -l app=tinyolly-ui
kubectl get deployments,services -l app=tinyolly-otlp-receiver
kubectl get deployments,services -l app=tinyolly-redis
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
kubectl delete -f tinyolly-otlp-receiver.yaml --ignore-not-found
kubectl delete -f redis.yaml --ignore-not-found

echo ""
echo "Waiting for pods to terminate..."
kubectl wait --for=delete pod -l app=tinyolly-redis --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=tinyolly-otlp-receiver --timeout=60s 2>/dev/null || true
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
