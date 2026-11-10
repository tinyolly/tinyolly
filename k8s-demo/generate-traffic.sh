#!/bin/bash

# Generate traffic to demo applications

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Demo app URL
FRONTEND_URL="http://localhost:5001"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly Demo Traffic Generator${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if frontend is accessible
if ! curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL/" | grep -q "200"; then
    echo -e "${YELLOW}⚠ Frontend not accessible at ${FRONTEND_URL}${NC}"
    echo -e "${YELLOW}Make sure:${NC}"
    echo -e "  1. Demo apps are deployed: ${CYAN}./deploy.sh${NC}"
    echo -e "  2. kind cluster is up: ${CYAN}./scripts/kind-up.sh${NC}"
    echo ""
    echo -e "${YELLOW}Attempting to generate traffic anyway...${NC}"
    echo ""
fi

echo -e "${CYAN}Generating traffic to demo application...${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Counter
REQUEST_COUNT=0

while true; do
    # Randomly choose an endpoint
    RAND=$((RANDOM % 100))
    
    if [ $RAND -lt 10 ]; then
        # 10% - Error endpoint
        ENDPOINT="/error"
        echo -e "${YELLOW}[$REQUEST_COUNT] Calling ${ENDPOINT}${NC}"
        curl -s "$FRONTEND_URL$ENDPOINT" > /dev/null
    elif [ $RAND -lt 30 ]; then
        # 20% - Calculate endpoint
        ENDPOINT="/calculate"
        echo -e "${GREEN}[$REQUEST_COUNT] Calling ${ENDPOINT}${NC}"
        curl -s "$FRONTEND_URL$ENDPOINT" > /dev/null
    elif [ $RAND -lt 50 ]; then
        # 20% - Hello endpoint
        ENDPOINT="/hello"
        echo -e "${GREEN}[$REQUEST_COUNT] Calling ${ENDPOINT}${NC}"
        curl -s "$FRONTEND_URL$ENDPOINT" > /dev/null
    else
        # 50% - Process order (complex multi-service trace)
        ENDPOINT="/process-order"
        echo -e "${CYAN}[$REQUEST_COUNT] Calling ${ENDPOINT} (distributed trace)${NC}"
        RESPONSE=$(curl -s "$FRONTEND_URL$ENDPOINT")
        
        # Show order status
        if echo "$RESPONSE" | grep -q '"status":"success"'; then
            ORDER_ID=$(echo "$RESPONSE" | grep -o '"order_id":[0-9]*' | cut -d':' -f2)
            echo -e "  ${GREEN}✓ Order $ORDER_ID completed${NC}"
        elif echo "$RESPONSE" | grep -q '"status":"failed"'; then
            echo -e "  ${YELLOW}⚠ Order failed${NC}"
        fi
    fi
    
    REQUEST_COUNT=$((REQUEST_COUNT + 1))
    
    # Random delay between requests
    DELAY=$(awk -v min=0.5 -v max=2.0 'BEGIN{srand(); print min+rand()*(max-min)}')
    sleep $DELAY
done

