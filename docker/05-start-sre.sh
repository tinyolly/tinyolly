#!/usr/bin/env bash
# Start the opt-in AI SRE agent next to a running core stack. Model: SRE_MODEL (default qwen3:8b) at SRE_LLM_URL (default: Ollama on the host).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
F=docker-compose-tinyolly-core-local.yml
docker compose -f "$F" --profile sre up -d --build tinyolly-sre
echo "AI SRE console: http://localhost:7173"
