---
title: "3. Add AI SRE"
description: "Add the TinyOlly AI SRE Agent: it watches your telemetry, investigates incidents and proposes fixes"
---

# 3. Add AI SRE

The agent watches TinyOlly. When something breaks, it investigates and proposes a fix. Fixes are never applied.

!!! note "Designed for a model on your LAN"
    Put your Ollama address in `SRE_LLM_URL`. To use Claude or OpenAI instead, see [AI SRE Details](ai-sre-details.md#choose-a-model).

```bash
SRE_LLM_URL=http://<your-ollama-host>:11434/v1 ./k8s/06-rebuild+deploy-sre.sh
kubectl port-forward deploy/tinyolly-sre 7173:8080
```

The script also deploys `tinyolly-k8s-state`, a small collector that reports container restarts and readiness. It has read-only, cluster-wide access to workload objects and events.

Keep the port-forward running.

## What you should see

The console at [http://localhost:7173](http://localhost:7173) says it is watching your telemetry. Give it a few minutes to learn what normal looks like.

Open an investigation and click **Show prompts & tool results** to see what the model was asked, what it replied, and each tool call with its arguments and actual result. The agent keeps these in memory (up to 20,000 characters per entry), so a restart clears them.

[![The TinyOlly AI SRE Agent console](images/ai-sre-console-light.png)](images/ai-sre-console-light.png)

Next: [Create Scenarios](scenarios.md)

## Optional: AI agents next to the shop

`k8s/06-rebuild+deploy-sre.sh --agents` adds three shopping bots that call the Astronomy Shop, a local LLM and an MCP tool
through [agentgateway](https://agentgateway.dev), deployed from agentregistry. TinyOlly then shows their traces, token
metrics and edges on the service map. It needs the [agentgateway-demo](https://github.com/stevelerner/agentgateway-demo)
repo next to this one; its `tinyolly/README.md` covers what to look at and how to remove it. The AI SRE Agent ignores these
services unless the add-on is deployed with `AGENTS_WATCH=1`.
