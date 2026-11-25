#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

echo "========================================================"
echo "  TinyOlly - Cleanup Demo Apps"
echo "========================================================"
echo ""

echo "Stopping and removing demo containers..."
docker compose -f docker-compose-demo.yml down 2>&1

echo ""
echo "✓ Demo apps removed"
echo ""
echo "TinyOlly core is still running."
echo "To stop core: cd ../docker && ./02-stop-core.sh"
echo ""

