---
title: "4. Create Scenarios"
description: "Break the demo shop and watch the AI SRE agent find the problem."
---

# 4. Create Scenarios

You break the demo shop. The AI SRE agent from step 3 finds the problem.

You need the shop port-forward from step 2:

```bash
kubectl port-forward svc/frontend-proxy 8080:8080
```

You also need the agent console at http://localhost:7173.

## Do this

1. Open http://localhost:8080/feature
2. Set `paymentFailure` to `50%` in its dropdown. It applies at once; there is no save button.

The agent is not told what you changed.

## What you should see

- Within a few minutes, checkout and payment turn red at http://localhost:5005.
- The agent adds an investigation to the console list with a name and status.
- Click it for the cause (payment) and proposed fixes. Fixes are never applied.

Then set the flag back to off. A few minutes later the agent marks the investigation resolved.

## Flags worth trying

| flag | value | what breaks |
| --- | --- | --- |
| paymentFailure | 50% | payment errors seen as checkout failures |
| paymentUnreachable | on | payment is unavailable |
| cartFailure | 75% | cart errors |
| adFailure | on | ad service errors |
| imageSlowLoad | 10sec | slow images |
| intlShippingSlowdown | 10sec | slow shipping on one path |

## Hands-off

One optional command flips flags on a timer and scores the agent:

```bash
./k8s/06-rebuild+deploy-sre.sh --demo
```

Details in [AI SRE Details](ai-sre-details.md).

Next: [Send Your Own Telemetry](send-telemetry.md)
