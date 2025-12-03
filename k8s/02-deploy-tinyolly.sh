#!/bin/bash
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Deploying TinyOlly to Kubernetes..."
echo "==================================="

# Apply all manifests in the k8s directory
kubectl apply -f "$SCRIPT_DIR"

echo ""
echo "Deployment applied successfully!"
echo "Run 'kubectl get pods' to check status."
echo ""
echo "TinyOlly UI will be available at: http://localhost:5002"
echo "If using minikube: Make sure 'minikube tunnel' is running"
