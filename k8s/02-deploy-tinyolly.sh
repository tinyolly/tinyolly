#!/bin/bash
# Don't use set -e here - we want to handle errors gracefully and not crash the terminal
set +e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Deploying TinyOlly to Kubernetes..."
echo "==================================="

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    echo "Please install kubectl: https://kubernetes.io/docs/tasks/tools/"
    return 2>/dev/null || exit 1
fi

# Check if connected to a cluster
echo "Checking cluster connection..."
if ! kubectl cluster-info &> /dev/null; then
    echo ""
    echo "Error: Not connected to a Kubernetes cluster"
    echo "Please ensure your cluster is running and kubectl is configured properly"
    echo ""
    echo "For kind on Colima:"
    echo "  1. Start cluster: ./scripts/colima-up.sh && ./scripts/kind-up.sh"
    echo "  2. Deploy: ./02-deploy-tinyolly.sh"
    echo ""
    return 2>/dev/null || exit 1
fi

echo "Cluster connection verified."
echo ""

# Apply only YAML files in the correct order (exclude shell scripts)
echo "Applying Kubernetes manifests..."

# Track if any step fails
FAILED=false

# 1. Apply ConfigMaps first (needed by otel-collector and UI)
echo "  → Creating ConfigMaps..."
if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/config.yaml" 2>/dev/null; then
    echo "    Warning: Validation failed, trying with --validate=false..."
    if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/config.yaml" --validate=false; then
        echo "    Error: Failed to create otel-collector-config ConfigMap"
        FAILED=true
    fi
fi
if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/supervisor.yaml" 2>/dev/null; then
    echo "    Warning: Validation failed, trying with --validate=false..."
    if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/supervisor.yaml" --validate=false; then
        echo "    Error: Failed to create otel-supervisor-config ConfigMap"
        FAILED=true
    fi
fi
if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/templates/prometheus-remote-write.yaml" 2>/dev/null; then
    echo "    Warning: Validation failed, trying with --validate=false..."
    if ! kubectl apply -f "$SCRIPT_DIR/otelcol-configs/templates/prometheus-remote-write.yaml" --validate=false; then
        echo "    Error: Failed to create otelcol-templates ConfigMap"
        FAILED=true
    fi
fi

# 2. Apply SQLite PVC (base dependency)
echo "  → Creating SQLite PVC..."
if ! kubectl apply -f "$SCRIPT_DIR/tinyolly-sqlite-pvc.yaml"; then
    echo "    Error: Failed to apply tinyolly-sqlite-pvc.yaml"
    FAILED=true
fi

# 3. Apply OTLP receiver
echo "  → Deploying OTLP receiver..."
if ! kubectl apply -f "$SCRIPT_DIR/tinyolly-otlp-receiver.yaml"; then
    echo "    Error: Failed to apply tinyolly-otlp-receiver.yaml"
    FAILED=true
fi

# 4. Apply OpAMP server (depends on ConfigMap)
echo "  → Deploying OpAMP server..."
if ! kubectl apply -f "$SCRIPT_DIR/tinyolly-opamp-server.yaml"; then
    echo "    Error: Failed to apply tinyolly-opamp-server.yaml"
    FAILED=true
fi

# 5. Apply OTel Collector (depends on ConfigMap, OTLP receiver, and OpAMP server)
echo "  → Deploying OTel Collector..."
if ! kubectl apply -f "$SCRIPT_DIR/otel-collector.yaml"; then
    echo "    Error: Failed to apply otel-collector.yaml"
    FAILED=true
fi

# 6. Apply UI (depends on OTel Collector and OpAMP server)
echo "  → Deploying TinyOlly UI..."
if ! kubectl apply -f "$SCRIPT_DIR/tinyolly-ui.yaml"; then
    echo "    Error: Failed to apply tinyolly-ui.yaml"
    FAILED=true
fi

# Check if deployment was successful
if [ "$FAILED" = true ]; then
    echo ""
    echo "Some deployments failed. Check the errors above."
    echo "You may need to:"
    echo "  1. Ensure the cluster is running: kind get clusters"
    echo "  2. Check kubectl context: kubectl config current-context"
    return 2>/dev/null || exit 1
fi

echo ""
echo "Deployment applied successfully!"
echo "Run 'kubectl get pods' to check status."
echo ""
echo "TinyOlly UI will be available at: http://localhost:5005 (kind port mapping, see scripts/kind-config.yaml)"
