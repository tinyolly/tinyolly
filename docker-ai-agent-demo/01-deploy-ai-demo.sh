#!/bin/bash
set +e  # Don't exit on errors

# Trap to prevent terminal exit
trap 'echo "Script interrupted"; exit 0' INT TERM

echo "========================================================"
echo "  TinyOlly - Deploy AI Agent Demo (Ollama + Auto-Instrumentation)"
echo "========================================================"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "✗ docker-compose is not installed or not in PATH"
    exit 1
fi

# Check if TinyOlly core is running
echo "Checking if TinyOlly core is running..."
if ! docker ps 2>/dev/null | grep -q "otel-collector"; then
    echo "✗ OTel Collector not found"
    echo ""
    echo "Please start TinyOlly core first:"
    echo "  cd ../docker"
    echo "  ./01-start-core.sh"
    echo ""
    exit 1
fi

if ! docker ps 2>/dev/null | grep -q "tinyolly-otlp-receiver"; then
    echo "✗ TinyOlly OTLP Receiver not found"
    echo ""
    echo "Please start TinyOlly core first:"
    echo "  cd ../docker"
    echo "  ./01-start-core.sh"
    echo ""
    exit 1
fi

echo "✓ TinyOlly core is running"
echo ""

# Deploy AI demo
echo "Deploying AI Agent demo with Ollama..."
echo ""
echo "NOTE: First run will pull the Ollama image and tinyllama model (~1.5GB total)."
echo "      This may take a few minutes..."
echo ""

docker-compose up -d
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to deploy AI agent demo (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

echo ""
echo "========================================================"
echo "  AI Agent Demo Deployed!"
echo "========================================================"
echo ""
echo "Services:"
echo "  - Ollama (tinyllama model): http://localhost:11434"
echo "  - AI Agent: generating traces every 15 seconds"
echo ""
echo "TinyOlly UI: http://localhost:5002"
echo "  → Click 'AI Agents' tab to see GenAI traces"
echo ""
echo "Watch agent logs:"
echo "  docker-compose logs -f ai-agent"
echo ""
echo "Watch Ollama logs:"
echo "  docker-compose logs -f ollama"
echo ""
echo "To stop AI demo:"
echo "  ./02-stop-ai-demo.sh"
echo ""
echo "To cleanup (remove volumes):"
echo "  ./03-cleanup-ai-demo.sh"
echo ""
