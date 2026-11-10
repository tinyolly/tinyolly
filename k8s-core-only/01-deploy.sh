#!/bin/bash

echo "Deploying TinyOlly Core (No Collector) to Kubernetes..."
echo "==================================="

# Apply ConfigMaps first
echo "Creating ConfigMaps..."
kubectl apply -f otelcol-configs/templates/templates.yaml

# Apply manifests
echo "Deploying services..."
kubectl apply -f tinyolly-sqlite-pvc.yaml
kubectl apply -f tinyolly-otlp-receiver.yaml
kubectl apply -f tinyolly-opamp-server.yaml
kubectl apply -f tinyolly-ui.yaml

echo ""
echo "Deployment applied successfully!"
echo "Run 'kubectl get pods' to check status."
echo ""
echo "TinyOlly UI will be available at: http://localhost:5002"
echo "(kind: UI is mapped to host port 5005 by scripts/kind-config.yaml)"
