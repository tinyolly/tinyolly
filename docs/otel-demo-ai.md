---
title: "Ask an AI about the OpenTelemetry Demo"
description: "Investigate the OpenTelemetry Demo (Astronomy Shop) in TinyOlly with an AI assistant over MCP: example prompts, a worked payment-failure investigation with screenshots and real tool output"
---

# Ask an AI about the OpenTelemetry Demo

Try TinyOlly's [MCP server](mcp.md) on the [OpenTelemetry Demo](otel-demo.md): real services, traces and logs, and failures you switch on with a flag. Ask an assistant (Claude Code, Claude Desktop, Zed) in plain English; it answers from TinyOlly's data.

Before you start: TinyOlly and the demo are running ([add the demo](otel-demo.md)), and the assistant is connected to `http://localhost:8765/mcp` ([set up and connect it](mcp-deploy.md)). "List the TinyOlly playbooks you have" should show `tinyolly-demo-failure-injection`.

[![The OpenTelemetry Demo as drawn by the MCP chart_service_map tool](images/mesh-otel-service-map.png)](images/full/mesh-otel-service-map.png)

## Prompts to try

**Explore**

| Prompt | Tool |
|---|---|
| "What services are running, and how healthy are they?" | `list_services` |
| "Show me the service map." | `chart_service_map` |
| "Draw the neighbourhood of checkout, two hops out." | `chart_service_map` |
| "How does an order flow through the shop?" | `search_traces`, `get_trace` |

**Investigate a failure**

| Prompt | Tool |
|---|---|
| "Something is wrong with checkout. What is failing and why?" | `get_service_map` (errors only), `search_traces`, `get_trace` |
| "Show me a failing order as a waterfall." | `search_traces` (errors only), `get_trace` (waterfall) |
| "Draw the journey of that failing request over the map." | `chart_trace_path` |
| "Explain the edge from checkout to payment: errors, latency." | `get_edge` |
| "Break payments for me, then show how TinyOlly catches it." | `get_skill` → `tinyolly-demo-failure-injection` |

**Dig deeper**

| Prompt | Tool |
|---|---|
| "Find the slowest checkout traces and tell me where the time goes." | `search_traces`, `get_trace_spans` |
| "Show the attributes of the payment span in that trace." | `get_span` |
| "Group `traces.span.metrics.calls` by service and status." | `query_metric` |
| "Are any card numbers or emails visible in span attributes?" (with the `emitRawPii` flag on) | `search_spans`, `get_span` |
| "Which metrics exist for the cart service?" | `list_metrics` |

**Learn the tool**

| Prompt | Tool |
|---|---|
| "How do I apply the PII redaction preset?" | `search_docs`, `read_doc` |
| "Which feature flags can I use to break the demo?" | `read_doc` |

## Worked example: payments start failing

A real run on kind with `paymentFailure` at 50%.

### 1. Break it

With the shop port-forward running (`kubectl port-forward svc/frontend-proxy 8080:8080`), open [http://localhost:8080/feature](http://localhost:8080/feature) and set `paymentFailure` to `50%`. Errors show within a minute or two.

### 2. Ask what is wrong

> Something is wrong with checkout. What is failing and why?

The catalog shows the two services whose error rate jumped, and `get_service_map` with `only="errors"` returns just the failing path (trimmed):

[![TinyOlly service catalog: checkout and payment at 15% errors](images/ui-otel-failure-catalog.png)](images/full/ui-otel-failure-catalog.png)

```json
{"nodes": [{"id": "frontend"}, {"id": "checkout"}, {"id": "payment"}],
 "edges": [{"source": "frontend", "target": "checkout", "error_count": 4, "p95": 59.03},
           {"source": "checkout", "target": "payment",  "error_count": 4, "p95": 8.6}]}
```

[![chart_service_map with checkout and payment outlined in red](images/mesh-otel-failure-map.png)](images/full/mesh-otel-failure-map.png)

### 3. Look at a failing order

> Show me a failing order as a waterfall.

`search_traces` (errors only, service `payment`) finds the traces and `get_trace` draws one (error spans `✗` shown; the tool also lists the slowest spans and how many it hid):

```text
Trace f8ff6711ece8e830e65a3142885cd309: 47.8ms, 100 spans, 7 errors, 9 services
  └ frontend-proxy: router frontend egress   │                   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  21.9ms ✗
        └ frontend: executing api route (pa… │                   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  21.2ms ✗
          └ frontend: grpc.oteldemo.Checkou… │                   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │  20.8ms ✗
            └ checkout: oteldemo.CheckoutSe… │                    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │  19.3ms ✗
              └ checkout: oteldemo.PaymentS… │                               ▓▓▓▓ │  5.09ms ✗
                └ payment: grpc.oteldemo.Pa… │                                 ▓▓ │  1.86ms ✗
                  └ payment: charge          │                                 ▓▓ │   902µs ✗
```

The failure starts in `payment: charge` and bubbles up to the proxy.

### 4. See the journey

> Draw the journey of that failing request over the map.

`chart_trace_path` numbers each hop with its time, failing services outlined in red:

[![chart_trace_path: the failing order's journey, with checkout and payment in red](images/mesh-otel-trace-path.png)](images/full/mesh-otel-trace-path.png)

### 5. Confirm with the edge

> Explain the edge from checkout to payment.

`get_edge` reports 18.18% errors on both ends and a p95 of about 7.5 ms at payment: the failures are fast, so payment rejects charges rather than timing out.

### 6. Turn it off and check

Set `paymentFailure` back to `off` at [http://localhost:8080/feature](http://localhost:8080/feature).

A minute or two later new orders stop failing, and the catalog's error rate decays as the window moves on.

## What the tools do not cover for this demo

`what_changed` lists change markers (such as the flag flips the AI SRE Agent's demo shift records), but its before/after comparison and `chart_map_diff` read Istio request metrics, so they show no differences for this demo, which has no mesh. The trace-based tools above work.

## See also

- [Add the Demo](otel-demo.md) and [Create Scenarios](scenarios.md): setup and failure flags
- [MCP tools and playbooks](mcp.md): every tool and playbook
- [Istio ambient demo](istio.md): the same ideas for a service mesh
