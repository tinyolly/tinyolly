#!/bin/bash

# Cleanup TinyOlly Demo Apps from Kubernetes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly Demo App Cleanup${NC}"
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
echo -e "${BLUE}Checking for demo resources...${NC}"
RESOURCES_EXIST=false

if kubectl get deployment demo-frontend &> /dev/null || \
   kubectl get deployment demo-backend &> /dev/null; then
    RESOURCES_EXIST=true
fi

if [ "$RESOURCES_EXIST" = false ]; then
    echo -e "${YELLOW}No demo resources found${NC}"
    echo ""
    echo -e "${GREEN}Nothing to clean up!${NC}"
    exit 0
fi

# Show resources that will be deleted
echo -e "${YELLOW}The following demo resources will be deleted:${NC}"
echo ""
kubectl get deployments,services 2>/dev/null | grep -E "(demo-frontend|demo-backend)" || echo "  (checking resources...)"
echo ""

# Confirm deletion
read -p "$(echo -e ${YELLOW}Do you want to proceed with cleanup? [y/N]:${NC} )" -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Deleting demo resources...${NC}"
echo ""

# Delete using manifests
echo -e "${YELLOW}→ Deleting demo frontend...${NC}"
kubectl delete -f "$SCRIPT_DIR/demo-frontend.yaml" --ignore-not-found=true 2>&1 | grep -v "error: the path" || true

echo -e "${YELLOW}→ Deleting demo backend...${NC}"
kubectl delete -f "$SCRIPT_DIR/demo-backend.yaml" --ignore-not-found=true 2>&1 | grep -v "error: the path" || true

# Ensure everything is deleted
echo ""
echo -e "${YELLOW}→ Ensuring all demo resources are deleted...${NC}"
kubectl delete deployment demo-frontend --ignore-not-found=true 2>/dev/null || true
kubectl delete deployment demo-backend --ignore-not-found=true 2>/dev/null || true
kubectl delete service demo-frontend --ignore-not-found=true 2>/dev/null || true
kubectl delete service demo-backend --ignore-not-found=true 2>/dev/null || true

# Wait for pods to terminate
echo ""
echo -e "${BLUE}Waiting for pods to terminate...${NC}"
kubectl wait --for=delete pod -l app=demo-frontend --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=demo-backend --timeout=60s 2>/dev/null || true

echo ""
echo -e "${BLUE}Verifying cleanup...${NC}"

# Check if any resources still exist
REMAINING_RESOURCES=false
if kubectl get deployment,service 2>/dev/null | grep -qE "(demo-frontend|demo-backend)"; then
    REMAINING_RESOURCES=true
    echo -e "${YELLOW}Warning: Some demo resources may still exist:${NC}"
    kubectl get deployment,service 2>/dev/null | grep -E "(demo-frontend|demo-backend)" || true
else
    echo -e "${GREEN}✓ All demo resources have been deleted${NC}"
fi

# Offer to clean up Docker images if using Minikube
if command -v minikube &> /dev/null && [ "$CONTEXT" = "minikube" ]; then
    echo ""
    read -p "$(echo -e ${YELLOW}Do you want to remove demo Docker images from Minikube? [y/N]:${NC} )" -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Removing Docker images from Minikube...${NC}"
        minikube ssh "docker images | grep demo | awk '{print \$1\":\"\$2}' | xargs -r docker rmi" 2>/dev/null || true
        echo -e "${GREEN}✓ Docker images removed${NC}"
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Demo cleanup complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Note: TinyOlly core services (SQLite, OTel Collector, UI) are still running${NC}"
echo -e "To remove them, run: ${CYAN}cd ../k8s && ./cleanup.sh${NC}"

