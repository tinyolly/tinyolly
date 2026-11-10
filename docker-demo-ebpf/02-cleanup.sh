#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

echo "Stopping eBPF demo..."
docker compose down

echo "Done."
