# AI Agent Demo

This demo showcases **GenAI observability** with OpenTelemetry - automatic instrumentation of LLM calls using the `opentelemetry-instrumentation-ollama` package.

## What is GenAI Observability?

GenAI observability captures telemetry from LLM interactions including:

- **Prompts and responses** - Full text of user prompts and model outputs
- **Token usage** - Input and output token counts
- **Latency** - Response time for each LLM call
- **Model information** - Which model was used

## Quick Start

### Docker

```bash
# Start TinyOlly core first
cd docker
./01-start-core.sh

# Deploy AI agent demo (pulls pre-built images from Docker Hub)
cd ../docker-ai-agent-demo
./01-deploy-ai-demo.sh
```

This starts:

- **Ollama** with TinyLlama model for local LLM inference
- **AI Agent** with automatic GenAI span instrumentation

Access the UI at `http://localhost:5005` and navigate to the **AI Agents** tab.

**For local development:** Use `./01-deploy-ai-demo-local.sh` to build locally

**Stop:** `./02-stop-ai-demo.sh`

**Cleanup (remove volumes):** `./03-cleanup-ai-demo.sh`

## How It Works

The demo uses zero-code auto-instrumentation - no OpenTelemetry imports in the application code:

```python
# agent.py - NO OpenTelemetry imports needed!
from ollama import Client

client = Client(host="http://ollama:11434")

# This call is AUTO-INSTRUMENTED
response = client.chat(
    model="tinyllama",
    messages=[{"role": "user", "content": "What is OpenTelemetry?"}]
)
```

The magic happens in the Dockerfile:

```dockerfile
# Install auto-instrumentation packages
RUN pip install opentelemetry-distro opentelemetry-instrumentation-ollama

# Run with auto-instrumentation wrapper
CMD ["opentelemetry-instrument", "python", "-u", "agent.py"]
```

## What You'll See

In the **AI Agents** tab:

| Field | Description |
|-------|-------------|
| **Prompt** | The user's input to the LLM |
| **Response** | The model's output |
| **Tokens In** | Number of input tokens |
| **Tokens Out** | Number of output tokens |
| **Latency** | Response time in milliseconds |
| **Model** | Model name (e.g., `tinyllama`) |

Click any row to expand the full span details in JSON format.

## Supported LLMs

The OpenTelemetry GenAI semantic conventions work with any instrumented LLM provider:

- **Ollama** - Local LLM inference (this demo)
- **OpenAI** - GPT models via `opentelemetry-instrumentation-openai`
- **Anthropic** - Claude models
- **Other providers** - Any with OpenTelemetry instrumentation

## Configuration

The demo is configured via environment variables in `docker-compose.yml`:

```yaml
ai-agent:
  environment:
    - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    - OTEL_SERVICE_NAME=ai-agent-demo
    - OLLAMA_HOST=http://ollama:11434
```

## Troubleshooting

**No AI traces appearing?**

- Ensure TinyOlly core is running
- Check agent logs: `cd docker-ai-agent-demo && docker compose logs ai-agent`
- Verify Ollama is ready: `docker compose logs ollama`

**Model download taking long?**

- TinyLlama is ~600MB, first download may take a few minutes
- The Ollama container is limited to 4 GB of RAM, so the default 4 GB Colima VM is too small: restart it larger, e.g. `colima stop -p tinyolly && COLIMA_MEMORY=8 ./scripts/colima-up.sh`
- Check Ollama logs for download progress

**Agent errors?**

- Ollama needs time to load the model after container starts
- The agent waits 10 seconds before first call
