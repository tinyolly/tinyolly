# Docker Compose deployment (retired, not maintained)

TinyOlly runs on Kubernetes (kind on Colima) only: see [Quick Start](../../docs/quickstart.md). These files are kept for
reference. Paths inside them were not updated, so they do not run from here as is. App source, Dockerfiles and collector
configs stay in `docker/`.

| Here | Was |
|---|---|
| `docker/` | `docker/*.sh`, `docker/docker-compose*.yml` |
| `docker-otel-demo/` | the OpenTelemetry Demo on Compose |
| `misc/docker/`, `misc/docker-core-only/` | extra and core-only Compose stacks |
| `scripts/docker-alt.sh` | second Compose stack on shifted ports |
| `docker.md` | the Docker deployment docs page |
