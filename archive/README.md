# archive: retired demos (not maintained)

Moved here on 2026-11-25. TinyOlly's demo is now the [OpenTelemetry Demo](../docs/otel-demo.md) and the
[TinyOlly AI SRE Agent](../docs/ai-sre.md); these are kept for reference only. Paths inside them were not updated, so they do
not run from here as is. The images they built are no longer part of `build/dockerhub/02-build-all.sh` or the release workflow.

| Folder | Was |
|---|---|
| `docker-demo/`, `k8s-demo/` | two Flask services with generated traffic (Docker, kind) |
| `docker-demo-ebpf/`, `k8s-demo-ebpf/` | eBPF zero-code tracing demo (Docker, kind) |
| `docker-ai-agent-demo/`, `k8s-ai-agent-demo/` | AI agent with Ollama/TinyLlama (GenAI traces), to be replaced by an AI shopper |
| `build/dockerhub/02-build-*.sh`, `03-push-*.sh`; `build/local/build-*-kind.sh` | image builds for the demos above |
| `docs/ebpf.md`, `docs/ai-agent.md` | their docs pages |

The Docker Compose deployment option is in [`docker-compose/`](docker-compose/README.md).
