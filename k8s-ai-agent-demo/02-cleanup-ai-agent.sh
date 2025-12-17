#!/bin/bash

# Cleanup TinyOlly AI Agent Demo from Kubernetes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly AI Agent Demo Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}✗ kubectl is not installed${NC}"
    exit 1
fi

# Check cluster connection
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}✗ Not connected to a Kubernetes cluster${NC}"
    exit 1
fi

# Get current context
CONTEXT=$(kubectl config current-context)
echo -e "${YELLOW}Current context: ${CONTEXT}${NC}"
echo ""

# Check if demo resources exist
echo -e "${BLUE}Checking for AI Agent demo resources...${NC}"
RESOURCES_EXIST=false

if kubectl get deployment ollama &> /dev/null || \
   kubectl get deployment ai-agent &> /dev/null; then
    RESOURCES_EXIST=true
fi

if [ "$RESOURCES_EXIST" = false ]; then
    echo -e "${YELLOW}No AI Agent demo resources found${NC}"
    echo ""
    echo -e "${GREEN}Nothing to clean up!${NC}"
    exit 0
fi

# Show resources that will be deleted
echo -e "${YELLOW}The following AI Agent demo resources will be deleted:${NC}"
echo ""
kubectl get deployments,services,pvc 2>/dev/null | grep -E "(ollama|ai-agent)" || echo "  (checking resources...)"
echo ""

# Confirm deletion
read -p "$(echo -e ${YELLOW}Do you want to proceed with cleanup? [y/N]:${NC} )" -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Deleting AI Agent demo resources...${NC}"
echo ""

# Delete using manifests
echo -e "${YELLOW}→ Deleting AI Agent application...${NC}"
kubectl delete -f "$SCRIPT_DIR/ai-agent.yaml" --ignore-not-found=true 2>&1 | grep -v "error: the path" || true

echo -e "${YELLOW}→ Deleting Ollama LLM server...${NC}"
kubectl delete -f "$SCRIPT_DIR/ollama.yaml" --ignore-not-found=true 2>&1 | grep -v "error: the path" || true

# Ensure everything is deleted
echo ""
echo -e "${YELLOW}→ Ensuring all demo resources are deleted...${NC}"
kubectl delete deployment ollama --ignore-not-found=true 2>/dev/null || true
kubectl delete deployment ai-agent --ignore-not-found=true 2>/dev/null || true
kubectl delete service ollama --ignore-not-found=true 2>/dev/null || true
kubectl delete service ai-agent --ignore-not-found=true 2>/dev/null || true

# Wait for pods to terminate
echo ""
echo -e "${BLUE}Waiting for pods to terminate...${NC}"
kubectl wait --for=delete pod -l app=ollama --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=ai-agent --timeout=60s 2>/dev/null || true

echo ""
echo -e "${BLUE}Verifying cleanup...${NC}"

# Check if any resources still exist
REMAINING_RESOURCES=false
if kubectl get deployment,service 2>/dev/null | grep -qE "(ollama|ai-agent)"; then
    REMAINING_RESOURCES=true
    echo -e "${YELLOW}Warning: Some demo resources may still exist:${NC}"
    kubectl get deployment,service 2>/dev/null | grep -E "(ollama|ai-agent)" || true
else
    echo -e "${GREEN}✓ All AI Agent demo resources have been deleted${NC}"
fi

# Ask about PVC deletion
echo ""
read -p "$(echo -e ${YELLOW}Do you want to delete the Ollama data volume (model data)? [y/N]:${NC} )" -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Deleting Ollama data volume...${NC}"
    kubectl delete pvc ollama-data --ignore-not-found=true 2>/dev/null || true
    echo -e "${GREEN}✓ Volume deleted${NC}"
    echo -e "${YELLOW}Note: Next deploy will need to re-download the tinyllama model${NC}"
else
    echo -e "${YELLOW}Keeping Ollama data volume (model will persist)${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}AI Agent demo cleanup complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Note: TinyOlly core services are still running${NC}"
echo -e "To remove them, run: ${CYAN}cd ../k8s && ./03-cleanup.sh${NC}"
echo ""
