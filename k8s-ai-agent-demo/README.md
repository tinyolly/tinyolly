# TinyOlly AI Agent Demo - Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the TinyOlly AI Agent Demo with Ollama LLM.

## Prerequisites

- Kubernetes cluster (minikube, kind, or cloud provider)
- kubectl configured
- TinyOlly core services deployed (see `../k8s/`)

## Resource Limits

The Ollama container is configured with CPU and memory limits to prevent excessive resource usage:

- **CPU Limit**: 2 cores (2000m)
- **CPU Request**: 0.5 cores (500m)
- **Memory Limit**: 4GB
- **Memory Request**: 1GB

## Deployment

```bash
# Deploy the AI Agent demo
./01-deploy-ai-agent.sh

# Check status
kubectl get pods -l app=ollama
kubectl get pods -l app=ai-agent

# View logs
kubectl logs -l app=ai-agent -f
```

## Cleanup

```bash
# Remove AI Agent demo (keeps model data by default)
./02-cleanup-ai-agent.sh
```

## Components

### Ollama LLM Server
- Runs the tinyllama model
- CPU limited to 2 cores
- Persistent storage for model data (10GB PVC)
- Health checks ensure model is loaded

### AI Agent Application
- Auto-instrumented with OpenTelemetry
- Sends traces to TinyOlly core
- Connects to Ollama for LLM inference

## Adjusting Resource Limits

To change CPU/memory limits, edit `ollama.yaml`:

```yaml
resources:
  limits:
    cpu: "2000m"      # Change this (1000m = 1 core)
    memory: "4Gi"     # Change this
  requests:
    cpu: "500m"       # Change this
    memory: "1Gi"     # Change this
```

Then reapply:
```bash
kubectl apply -f ollama.yaml
kubectl rollout restart deployment/ollama
```
