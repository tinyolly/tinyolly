#!/usr/bin/env bash
# gofmt + go vet + go test -race for the OpAMP server, in the pinned golang image (no local Go needed).
set -euo pipefail
cd "$(dirname "$0")/.."
GO_VERSION=$(grep '^GO_VERSION=' versions.env | cut -d= -f2 | awk '{print $1}')
docker run --rm -v "$PWD/docker/apps/tinyolly-opamp-server":/src -w /src "golang:${GO_VERSION}-alpine" sh -c '
  apk add -q build-base >/dev/null 2>&1
  unformatted=$(gofmt -l .); [ -z "$unformatted" ] || { echo "gofmt needed: $unformatted"; exit 1; }
  go vet ./...
  CGO_ENABLED=1 go test -race ./...
'
