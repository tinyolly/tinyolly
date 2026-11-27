---
title: "1. Quick Start"
description: "Get TinyOlly running on a Mac, on Kubernetes (kind) inside a Colima VM."
---

# 1. Quick Start

This page gets TinyOlly running on a Mac. It uses Kubernetes (kind) inside a Colima VM. You need an Apple Silicon Mac with 24 GB or more.

```bash
brew install colima docker kubectl kind helm
git clone https://github.com/tinyolly/tinyolly && cd tinyolly
./scripts/colima-up.sh
./scripts/kind-up.sh
./k8s/02-deploy-tinyolly.sh
kubectl get pods
```

## What you should see

All pods are Running. The UI is at [http://localhost:5005](http://localhost:5005). It is empty until something sends telemetry, apart from TinyOlly itself.

For sizes, ports, cleanup and troubleshooting, see [Kubernetes](kubernetes.md).

Next: [Add the Demo](otel-demo.md)
