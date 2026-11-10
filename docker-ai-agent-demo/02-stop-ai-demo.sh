#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

echo "========================================================"
echo "  TinyOlly - Stop AI Agent Demo"
echo "========================================================"
echo ""

echo "Stopping AI Agent demo containers..."
docker compose down 2>&1

echo ""
echo "✓ AI Agent demo stopped"
echo ""
echo "Note: Ollama model data is preserved in the volume."
echo "To remove volumes and model data, run: ./03-cleanup-ai-demo.sh"
echo ""
echo "TinyOlly core is still running."
echo "To stop core: cd ../docker && ./02-stop-core.sh"
echo ""
