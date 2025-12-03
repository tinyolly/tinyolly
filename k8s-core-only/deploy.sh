#!/bin/bash

echo "Deploying TinyOlly Core (No Collector) to Kubernetes..."
echo "==================================="

# Apply manifests
kubectl apply -f redis.yaml
kubectl apply -f tinyolly-otlp-receiver.yaml
kubectl apply -f tinyolly-ui.yaml

echo ""
echo "Deployment applied successfully!"
echo "Run 'kubectl get pods' to check status."
echo ""
echo "TinyOlly UI will be available at: http://localhost:5002"
echo "If using minikube: Make sure 'minikube tunnel' is running"
