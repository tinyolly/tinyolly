#!/bin/bash
set -e

# Build ALL TinyOlly images locally (multi-arch)
# Usage: ./02-build-all.sh [version]
# Example: ./02-build-all.sh v2.1.0
#
# This builds: core, demo, ebpf-demo, and ai-demo images
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

# Build demo images
echo ""
echo ">>> Building Demo Images..."
echo ""
"$SCRIPT_DIR/02-build-demo.sh" "$VERSION"

# Build eBPF demo images
echo ""
echo ">>> Building eBPF Demo Images..."
echo ""
"$SCRIPT_DIR/02-build-ebpf-demo.sh" "$VERSION"

# Build AI demo image
echo ""
echo ">>> Building AI Demo Image..."
echo ""
"$SCRIPT_DIR/02-build-ai-demo.sh" "$VERSION"

echo ""
echo "=========================================="
echo "✓ ALL images built locally!"
echo "=========================================="
echo ""
echo "Core images:"
echo "  - tinyolly/python-base:$VERSION"
echo "  - tinyolly/otlp-receiver:$VERSION"
echo "  - tinyolly/ui:$VERSION"
echo "  - tinyolly/opamp-server:$VERSION"
echo "  - tinyolly/otel-supervisor:$VERSION"
echo ""
echo "Demo images:"
echo "  - tinyolly/demo-frontend:$VERSION"
echo "  - tinyolly/demo-backend:$VERSION"
echo ""
echo "eBPF Demo images:"
echo "  - tinyolly/ebpf-frontend:$VERSION"
echo "  - tinyolly/ebpf-backend:$VERSION"
echo ""
echo "AI Demo image:"
echo "  - tinyolly/ai-agent-demo:$VERSION"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-all.sh $VERSION"
echo ""
