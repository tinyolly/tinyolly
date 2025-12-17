#!/bin/bash

# Deploy TinyOlly AI Agent Demo to Kubernetes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly AI Agent Demo Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}✗ kubectl is not installed${NC}"
    echo "Please install kubectl: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

# Check if connected to a cluster
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}✗ Not connected to a Kubernetes cluster${NC}"
    echo "Please ensure your cluster is running and kubectl is configured properly"
    exit 1
fi

# Get current context
CONTEXT=$(kubectl config current-context)
echo -e "${YELLOW}Current context: ${CONTEXT}${NC}"
echo ""

# Check if TinyOlly core is running
echo -e "${BLUE}Checking TinyOlly core services...${NC}"
if ! kubectl get service tinyolly-redis &> /dev/null || \
   ! kubectl get service otel-collector &> /dev/null; then
    echo -e "${YELLOW}Warning: TinyOlly core services may not be running${NC}"
    echo -e "${YELLOW}Make sure to deploy core first: cd ../k8s && ./01-deploy.sh${NC}"
    echo ""
    read -p "$(echo -e ${YELLOW}Continue anyway? [y/N]:${NC} )" -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Deployment cancelled${NC}"
        exit 0
    fi
fi

echo ""
echo -e "${BLUE}Deploying AI Agent Demo...${NC}"
echo ""

# Deploy Ollama
echo -e "${YELLOW}→ Deploying Ollama LLM server...${NC}"
kubectl apply -f "$SCRIPT_DIR/ollama.yaml"

# Deploy AI Agent
echo -e "${YELLOW}→ Deploying AI Agent application...${NC}"
kubectl apply -f "$SCRIPT_DIR/ai-agent.yaml"

echo ""
echo -e "${BLUE}Waiting for pods to be ready...${NC}"
echo ""

# Wait for Ollama
echo -e "${YELLOW}→ Waiting for Ollama (this may take 2-3 minutes to download the model)...${NC}"
kubectl wait --for=condition=ready pod -l app=ollama --timeout=300s 2>&1 || {
    echo -e "${YELLOW}  Still starting up, checking status...${NC}"
    kubectl get pods -l app=ollama
}

# Wait for AI Agent
echo -e "${YELLOW}→ Waiting for AI Agent...${NC}"
kubectl wait --for=condition=ready pod -l app=ai-agent --timeout=120s 2>&1 || {
    echo -e "${YELLOW}  Still starting up, checking status...${NC}"
    kubectl get pods -l app=ai-agent
}

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}AI Agent Demo deployed!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Show pod status
echo -e "${YELLOW}Pod Status:${NC}"
kubectl get pods -l app=ollama -o wide
kubectl get pods -l app=ai-agent -o wide
echo ""

# Show services
echo -e "${YELLOW}Services:${NC}"
kubectl get services -l app=ollama
kubectl get services -l app=ai-agent
echo ""

echo -e "${CYAN}Note: Ollama is limited to 2 CPU cores and 4GB RAM${NC}"
echo -e "${CYAN}To access the AI Agent, use port-forwarding or expose via LoadBalancer/Ingress${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  • Check logs: kubectl logs -l app=ai-agent"
echo "  • Port forward: kubectl port-forward svc/ai-agent 8000:80"
echo ""
