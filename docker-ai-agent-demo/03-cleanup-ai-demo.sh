#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

echo "========================================================"
echo "  TinyOlly - Cleanup AI Agent Demo (Full)"
echo "========================================================"
echo ""

echo "Stopping and removing AI Agent demo containers..."
docker compose down 2>&1

echo ""
echo "Removing Ollama volume (model data)..."
docker volume rm docker-ai-agent-demo_ollama-data 2>/dev/null || echo "Volume not found or already removed"

echo ""
echo "✓ AI Agent demo fully cleaned up"
echo ""
echo "Note: Next deploy will need to re-download the tinyllama model."
echo ""
echo "TinyOlly core is still running."
echo "To stop core: cd ../docker && ./02-stop-core.sh"
echo ""
