#!/bin/bash

# Deploy TinyOlly Demo Apps to Kubernetes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly Demo App Deployment${NC}"
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

CONTEXT=$(kubectl config current-context)
echo -e "${CYAN}Cluster context: ${CONTEXT}${NC}"
echo ""

# Check if TinyOlly core is deployed
echo -e "${CYAN}Checking TinyOlly core services...${NC}"
if ! kubectl get service otel-collector &> /dev/null; then
    echo -e "${RED}✗ OTel Collector service not found${NC}"
    echo -e "${YELLOW}Please deploy TinyOlly core first:${NC}"
    echo -e "  cd ../k8s"
    echo -e "  kubectl apply -f ."
    exit 1
fi
echo -e "${GREEN}✓ TinyOlly core services found${NC}"
echo ""

# Check if using the local kind cluster
USE_KIND=false
RESTORE_MANIFESTS=false
if [ "$CONTEXT" = "kind-tinyolly" ]; then
    USE_KIND=true
fi

# Build images if using kind (optional - will pull from Docker Hub by default)
if [ "$USE_KIND" = true ]; then
    echo -e "${CYAN}Note: Images will be pulled from Docker Hub by default.${NC}"
    echo -e "${CYAN}Do you want to build images locally instead? [y/N]:${NC} "
    read -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${CYAN}Building demo images locally...${NC}"
        bash "$SCRIPT_DIR/../build/local/build-demo-kind.sh"

        if [ $? -ne 0 ]; then
            echo -e "${RED}✗ Failed to build images${NC}"
            exit 1
        fi

        # Update manifests to use local images
        echo -e "${CYAN}Updating manifests for local images...${NC}"
        sed -i.bak 's/imagePullPolicy: Always/imagePullPolicy: Never/' "$SCRIPT_DIR/demo-frontend.yaml"
        sed -i.bak 's/imagePullPolicy: Always/imagePullPolicy: Never/' "$SCRIPT_DIR/demo-backend.yaml"
        sed -i.bak 's|image: tinyolly/demo-frontend:latest|image: demo-frontend:latest|' "$SCRIPT_DIR/demo-frontend.yaml"
        sed -i.bak 's|image: tinyolly/demo-backend:latest|image: demo-backend:latest|' "$SCRIPT_DIR/demo-backend.yaml"

        # Set cleanup flag
        RESTORE_MANIFESTS=true
    else
        echo -e "${GREEN}✓ Will pull images from Docker Hub (tinyolly/demo-frontend:latest, tinyolly/demo-backend:latest)${NC}"
    fi
    echo ""
fi

# Deploy demo apps
echo -e "${CYAN}Deploying demo applications...${NC}"

kubectl apply -f "$SCRIPT_DIR/demo-backend.yaml"
kubectl apply -f "$SCRIPT_DIR/demo-frontend.yaml"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to apply manifests${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Manifests applied${NC}"
echo ""

# Wait for deployments
echo -e "${CYAN}Waiting for deployments to be ready...${NC}"
echo -e "${YELLOW}This may take a minute...${NC}"
echo ""

kubectl wait --for=condition=available --timeout=120s deployment/demo-backend 2>&1 || echo -e "${YELLOW}Backend not ready yet${NC}"
kubectl wait --for=condition=available --timeout=120s deployment/demo-frontend 2>&1 || echo -e "${YELLOW}Frontend not ready yet${NC}"

echo ""

# Check status
echo -e "${CYAN}Deployment status:${NC}"
kubectl get pods -l 'app in (demo-frontend,demo-backend)'
echo ""
kubectl get services -l 'app in (demo-frontend,demo-backend)'

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Demo Deployment Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ "$USE_KIND" = true ]; then
    echo -e "${CYAN}Access the demo:${NC}"
    echo -e "1. Ports are mapped by ${YELLOW}scripts/kind-config.yaml${NC}"
    echo -e "2. TinyOlly UI: ${GREEN}http://localhost:5005${NC}"
    echo -e "3. Demo Frontend: ${GREEN}http://localhost:5001${NC}"
    echo ""
    echo -e "${CYAN}Auto-Traffic:${NC}"
    echo -e "The demo apps ${GREEN}automatically generate traffic${NC} every 3-8 seconds."
    echo -e "Watch traces, logs, and metrics appear in the TinyOlly UI!"
    echo ""
    echo -e "${CYAN}Optional - Generate additional traffic:${NC}"
    echo -e "  ${YELLOW}./generate-traffic.sh${NC}"
fi

# Restore manifests if they were modified for local builds
if [ "$RESTORE_MANIFESTS" = true ]; then
    echo -e "${CYAN}Restoring manifests to Docker Hub defaults...${NC}"
    mv "$SCRIPT_DIR/demo-frontend.yaml.bak" "$SCRIPT_DIR/demo-frontend.yaml" 2>/dev/null || true
    mv "$SCRIPT_DIR/demo-backend.yaml.bak" "$SCRIPT_DIR/demo-backend.yaml" 2>/dev/null || true
fi

