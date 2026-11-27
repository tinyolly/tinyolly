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

[![The TinyOlly AI SRE Agent console](images/ai-sre-console-light.png)](images/ai-sre-console-light.png)

Next: [Create Scenarios](scenarios.md)
