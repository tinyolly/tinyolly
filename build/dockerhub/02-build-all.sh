#!/bin/bash

# Always use the Colima docker daemon (profile: COLIMA_PROFILE, default tinyolly)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
set -e

# Build ALL TinyOlly images locally (native arch)
# Usage: ./02-build-all.sh [version]
# Example: ./02-build-all.sh v2.1.0
#
# This builds: core images and the TinyOlly AI SRE Agent image (the old demo images are in archive/build)
# To push after building, run: ./03-push-all.sh [version]

VERSION=${1:-"latest"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "TinyOlly - Build ALL Images (No Push)"
echo "=========================================="
echo "Version: $VERSION"
echo ""

# Build core images
echo ""
echo ">>> Building Core Images..."
echo ""
"$SCRIPT_DIR/02-build-core.sh" "$VERSION"

# Build the TinyOlly AI SRE Agent image
echo ""
echo ">>> Building AI SRE Agent Image..."
echo ""
"$SCRIPT_DIR/02-build-sre.sh" "$VERSION"

echo ""
echo "=========================================="
echo "✓ ALL images built locally!"
echo "=========================================="
echo ""
echo "Core images:"
echo "  - tinyolly/python-base:$VERSION"
echo "  - tinyolly/otlp-receiver:$VERSION"
echo "  - tinyolly/ui:$VERSION"
echo "  - tinyolly/mcp:$VERSION"
echo "  - tinyolly/opamp-server:$VERSION"
echo "  - tinyolly/otel-supervisor:$VERSION"
echo "  - tinyolly/sre:$VERSION   (TinyOlly AI SRE Agent)"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-all.sh $VERSION"
echo ""
