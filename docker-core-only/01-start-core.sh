#!/bin/bash
set +e  # Don't exit on errors

echo "Starting TinyOlly Core (No OTel Collector)"
echo "=================================================="
echo ""
echo "Starting observability stack:"
echo "  - TinyOlly OTLP Receiver (listening on 4317)"
echo "  - Redis"
echo "  - TinyOlly Frontend (web UI)"
echo ""
echo "NOTE: No OpenTelemetry Collector included."
echo "      Use your external collector (e.g., Elastic EDOT) and point it to:"
echo "      http://tinyolly-otlp-receiver:4317"
echo ""

echo "Starting services..."
echo ""

docker compose -f docker-compose-tinyolly-core.yml up -d --build --force-recreate 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to start core services (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

echo ""
echo "Services started!"
echo ""

echo "TinyOlly UI:    http://localhost:5005"
echo "OTLP Endpoint:  localhost:4319 (gRPC only, for external collector)"
echo ""
echo "Next steps:"
echo "  1. Configure your external collector to send to: localhost:4319 (gRPC)"
echo "     Note: TinyOlly receiver only supports gRPC. For HTTP, use a collector that"
echo "           accepts HTTP and forwards via gRPC."
echo "  2. Open TinyOlly UI: open http://localhost:5005"
echo "  3. Stop services:    ./02-stop-core.sh"
echo ""

