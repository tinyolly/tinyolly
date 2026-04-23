#!/bin/bash
set +e  # Continue cleanup even if one step fails

echo "Stopping TinyOlly Core services..."
echo ""

COMPOSE_FILES=(
	"docker-compose-tinyolly-core.yml"
	"docker-compose-tinyolly-core-local.yml"
)

for compose_file in "${COMPOSE_FILES[@]}"; do
	if [ -f "$compose_file" ]; then
		echo "Bringing down stack from $compose_file"
		docker compose -f "$compose_file" down --remove-orphans --volumes 2>&1
	fi
done

# Fixed container names can outlive compose project metadata.
for c in tinyolly-ui tinyolly-opamp-server tinyolly-otlp-receiver; do
	if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
		echo "Removing leftover container: $c"
		docker rm -f "$c" >/dev/null 2>&1
	fi
done

# Remove stack-scoped network and volume if present.
docker network rm tinyolly-core-network >/dev/null 2>&1
docker volume rm tinyolly-db-data >/dev/null 2>&1

echo ""
echo "Cleanup complete."
