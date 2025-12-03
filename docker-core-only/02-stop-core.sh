#!/bin/bash
set -e

echo "Stopping TinyOlly Core services..."

docker compose -f docker-compose-tinyolly-core.yml down

echo "Services stopped."

