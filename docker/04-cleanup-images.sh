#!/bin/bash
set +e  # Don't exit on errors

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly - Local Docker Images Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Find all TinyOlly-related images
echo -e "${BLUE}Searching for TinyOlly Docker images...${NC}"
echo ""

IMAGES=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "tinyolly|demo-frontend|demo-backend" || true)

if [ -z "$IMAGES" ]; then
    echo -e "${YELLOW}No TinyOlly-related images found${NC}"
    echo ""
    echo -e "${GREEN}Nothing to clean up!${NC}"
    exit 0
fi

# Display images that will be removed
echo -e "${YELLOW}The following Docker images will be removed:${NC}"
echo ""
docker images | grep -E "REPOSITORY|tinyolly|demo-frontend|demo-backend"
echo ""

# Calculate total size
TOTAL_SIZE=$(docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | grep -E "tinyolly|demo-frontend|demo-backend" | awk '{print $2}' | sed 's/MB//;s/GB/*1024/;s/KB\/1024/' | bc 2>/dev/null | awk '{sum+=$1} END {printf "%.1f", sum}' || echo "unknown")
echo -e "${BLUE}Total size: ${TOTAL_SIZE}MB${NC}"
echo ""

# Confirm deletion
read -p "$(echo -e ${YELLOW}Do you want to remove these images? [y/N]:${NC} )" -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Removing Docker images...${NC}"
echo ""

# Remove each image
COUNT=0
for IMAGE in $IMAGES; do
    echo -e "${YELLOW}→ Removing ${IMAGE}...${NC}"
    if docker rmi "$IMAGE" 2>/dev/null; then
        COUNT=$((COUNT + 1))
    else
        echo -e "${RED}  Failed to remove ${IMAGE} (may be in use)${NC}"
    fi
done

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Cleanup complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}✓ Removed ${COUNT} image(s)${NC}"
echo ""

# Check if any images remain
REMAINING=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "tinyolly|demo-frontend|demo-backend" || true)
if [ -n "$REMAINING" ]; then
    echo -e "${YELLOW}Note: Some images could not be removed (likely in use by running containers):${NC}"
    docker images | grep -E "REPOSITORY|tinyolly|demo-frontend|demo-backend"
    echo ""
    echo -e "${YELLOW}Stop containers first with:${NC}"
    echo "  ./02-stop-core.sh"
    echo "  cd ../docker-demo && docker compose down"
    echo "  cd ../docker-ai-agent-demo && docker compose down"
fi

echo ""
echo -e "${BLUE}To clean up dangling images and build cache, run:${NC}"
echo "  docker image prune -a"
echo ""
