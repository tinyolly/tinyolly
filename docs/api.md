# REST API & OpenAPI

<div align="center">
  <img src="../images/metrics.png" alt="TinyOlly REST API" width="600">
  <p><em>Metrics accessible via the REST API</em></p>
</div>

---

TinyOlly provides a comprehensive REST API for programmatic access to all telemetry data in **OpenTelemetry-native format**.

## Interactive API Documentation

Access the auto-generated OpenAPI documentation:
- **Swagger UI**: `http://localhost:5005/docs` - Interactive API explorer
- **ReDoc**: `http://localhost:5005/redoc` - Alternative documentation
- **OpenAPI Spec**: `http://localhost:5005/openapi.json` - Machine-readable schema

All APIs return **OpenTelemetry-native JSON** with:
- **Resources**: `service.name`, `host.name`, etc.
- **Attributes**: Metric labels and span attributes
- **Full Context**: Trace/span IDs, timestamps, status codes

---

## API Endpoints Overview

The REST API provides endpoints for:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/traces` | GET | List recent traces with filtering |
| `/api/traces/{trace_id}` | GET | Get detailed trace with all spans |
| `/api/spans` | GET | List recent spans with filtering |
| `/api/logs` | GET | Retrieve logs with trace correlation |
| `/api/metrics` | GET | Query time-series metrics |
| `/api/service-map` | GET | Get service dependency graph |
| `/api/service-catalog` | GET | List services with RED metrics |
| `/api/stats` | GET | System stats and cardinality info |
| `/admin/stats` | GET | Detailed admin statistics |
| `/health` | GET | Health check endpoint |

All endpoints return data in standard OpenTelemetry format, ensuring compatibility with OpenTelemetry tooling and standards.

---

## Common API Workflows

### 1. Get All Recent Traces

Retrieve the last 50 traces:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/traces?limit=50
    ```

=== "Python"
    ```python
    import requests

    response = requests.get('http://localhost:5005/api/traces', params={'limit': 50})
    traces = response.json()

    for trace in traces:
        print(f"Trace {trace['trace_id']}: {trace['service_name']} - {trace['name']}")
    ```

=== "JavaScript"
    ```javascript
    fetch('http://localhost:5005/api/traces?limit=50')
      .then(response => response.json())
      .then(traces => {
        traces.forEach(trace => {
          console.log(`Trace ${trace.trace_id}: ${trace.service_name} - ${trace.name}`);
        });
      });
    ```

**Response Format:**
```json
[
  {
    "trace_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    "service_name": "demo-frontend",
    "name": "GET /products",
    "start_time": 1701234567890000000,
    "duration_ms": 125.4,
    "status_code": 200,
    "method": "GET",
    "route": "/products",
    "span_count": 5
  }
]
```

---

### 2. Get Detailed Trace with Waterfall

Retrieve a complete trace with all spans for waterfall visualization:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/traces/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
    ```

=== "Python"
    ```python
    import requests

    trace_id = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    response = requests.get(f'http://localhost:5005/api/traces/{trace_id}')
    trace = response.json()

    print(f"Trace: {trace['name']}")
    print(f"Total spans: {len(trace['spans'])}")
    print(f"Duration: {trace['duration_ms']}ms")

    for span in trace['spans']:
        indent = "  " * span.get('level', 0)
        print(f"{indent}{span['name']} ({span['duration_ms']}ms)")
    ```

**Response Format:**
```json
{
  "trace_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "name": "GET /products",
  "service_name": "demo-frontend",
  "start_time": 1701234567890000000,
  "duration_ms": 125.4,
  "span_count": 5,
  "spans": [
    {
      "span_id": "1234567890abcdef",
      "parent_span_id": null,
      "name": "GET /products",
      "service_name": "demo-frontend",
      "start_time": 1701234567890000000,
      "duration_ms": 125.4,
      "status": {"code": 1},
      "attributes": {
        "http.method": "GET",
        "http.route": "/products",
        "http.status_code": 200
      }
    }
  ]
}
```

---

### 3. Find Logs for a Specific Trace

Correlate logs with a trace using trace_id:

=== "cURL"
    ```bash
    curl "http://localhost:5005/api/logs?trace_id=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    ```

=== "Python"
    ```python
    import requests

    trace_id = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    response = requests.get('http://localhost:5005/api/logs',
                           params={'trace_id': trace_id})
    logs = response.json()

    for log in logs:
        print(f"[{log['severity']}] {log['body']}")
    ```

**Response Format:**
```json
[
  {
    "timestamp": 1701234567890000000,
    "trace_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    "span_id": "1234567890abcdef",
    "severity": "INFO",
    "body": "Processing product request",
    "service_name": "demo-frontend",
    "attributes": {
      "user_id": "12345"
    }
  }
]
```

---

### 4. Query Metrics

Retrieve metrics data:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/metrics
    ```

=== "Python"
    ```python
    import requests

    response = requests.get('http://localhost:5005/api/metrics')
    metrics = response.json()

    for metric in metrics:
        print(f"{metric['name']} ({metric['type']})")
        for series in metric.get('series', []):
            labels = ', '.join(f"{k}={v}" for k, v in series.get('attributes', {}).items())
            print(f"  [{labels}] = {series.get('value', 'N/A')}")
    ```

**Response Format:**
```json
[
  {
    "name": "http.server.duration",
    "type": "histogram",
    "description": "HTTP request duration",
    "unit": "ms",
    "series": [
      {
        "attributes": {
          "http.method": "GET",
          "http.route": "/products",
          "service.name": "demo-frontend"
        },
        "data_points": [
          {
            "timestamp": 1701234567890000000,
            "count": 42,
            "sum": 5250.5,
            "bucket_counts": [10, 20, 10, 2]
          }
        ]
      }
    ]
  }
]
```

---

### 5. Get Service Catalog with RED Metrics

List all services with Rate, Errors, and Duration metrics:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/service-catalog
    ```

=== "Python"
    ```python
    import requests

    response = requests.get('http://localhost:5005/api/service-catalog')
    services = response.json()

    for service in services:
        print(f"\n{service['service_name']}")
        print(f"  Request Rate: {service.get('request_rate', 0):.2f} req/s")
        print(f"  Error Rate: {service.get('error_rate', 0):.2f}%")
        print(f"  P50 Latency: {service.get('p50_latency', 0):.2f}ms")
        print(f"  P95 Latency: {service.get('p95_latency', 0):.2f}ms")
    ```

**Response Format:**
```json
[
  {
    "service_name": "demo-frontend",
    "span_count": 1523,
    "request_rate": 12.5,
    "error_rate": 2.3,
    "p50_latency": 45.2,
    "p95_latency": 125.7,
    "p99_latency": 250.3,
    "first_seen": 1701234567890000000,
    "last_seen": 1701238167890000000
  }
]
```

---

### 6. Get Service Dependency Map

Retrieve the service dependency graph:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/service-map
    ```

=== "Python"
    ```python
    import requests

    response = requests.get('http://localhost:5005/api/service-map')
    graph = response.json()

    print("Services:", len(graph['nodes']))
    for node in graph['nodes']:
        print(f"  - {node['service_name']} ({node['type']})")

    print("\nConnections:", len(graph['edges']))
    for edge in graph['edges']:
        print(f"  {edge['source']} → {edge['target']} ({edge['call_count']} calls)")
    ```

**Response Format:**
```json
{
  "nodes": [
    {
      "service_name": "demo-frontend",
      "type": "server",
      "span_count": 1523
    },
    {
      "service_name": "demo-backend",
      "type": "server",
      "span_count": 3046
    }
  ],
  "edges": [
    {
      "source": "demo-frontend",
      "target": "demo-backend",
      "call_count": 1523
    }
  ]
}
```

---

### 7. Check System Statistics

Get Redis memory usage and cardinality metrics:

=== "cURL"
    ```bash
    curl http://localhost:5005/api/stats
    ```

=== "Python"
    ```python
    import requests

    response = requests.get('http://localhost:5005/api/stats')
    stats = response.json()

    print(f"Total Traces: {stats.get('total_traces', 0)}")
    print(f"Total Spans: {stats.get('total_spans', 0)}")
    print(f"Total Logs: {stats.get('total_logs', 0)}")
    print(f"Total Metrics: {stats.get('total_metrics', 0)}")
    print(f"Unique Metric Names: {stats.get('unique_metric_names', 0)}")
    print(f"Redis Memory: {stats.get('redis_memory_mb', 0):.2f} MB")
    ```

**Response Format:**
```json
{
  "total_traces": 1523,
  "total_spans": 7615,
  "total_logs": 15230,
  "total_metrics": 45,
  "unique_metric_names": 12,
  "redis_memory_mb": 45.7,
  "cardinality_limit": 1000,
  "cardinality_usage_pct": 1.2,
  "uptime_seconds": 3600
}
```

---

## Advanced Filtering

### Filter Spans by Service

```bash
curl "http://localhost:5005/api/spans?service=demo-frontend&limit=100"
```

### Filter Logs by Severity

```bash
curl "http://localhost:5005/api/logs?severity=ERROR&limit=50"
```

### Time-based Queries

All endpoints support `start_time` and `end_time` parameters (Unix nanoseconds):

```bash
# Get traces from the last hour
START=$(date -u -d '1 hour ago' +%s)000000000
END=$(date -u +%s)000000000
curl "http://localhost:5005/api/traces?start_time=$START&end_time=$END"
```

---

## Client Generation

Generate API clients in any language using the OpenAPI spec:

```bash
# Download OpenAPI spec
curl http://localhost:5005/openapi.json > tinyolly-openapi.json

# Generate Python client
openapi-generator-cli generate \
  -i tinyolly-openapi.json \
  -g python \
  -o ./tinyolly-python-client

# Generate Go client
openapi-generator-cli generate \
  -i tinyolly-openapi.json \
  -g go \
  -o ./tinyolly-go-client

# Generate TypeScript client
openapi-generator-cli generate \
  -i tinyolly-openapi.json \
  -g typescript-fetch \
  -o ./tinyolly-ts-client
```

---

## Rate Limits

TinyOlly is designed for local development and has no rate limits. However:

- **Memory limits** apply based on Redis configuration (default: 256MB)
- **Cardinality protection** limits unique metric names to 1000 (configurable)
- **TTL**: All data expires after 30 minutes

---

## Authentication

TinyOlly is designed for local development and does **not** include authentication. Do not expose TinyOlly to the internet without adding authentication via a reverse proxy.

---

## Need Help?

- [View interactive examples in Swagger UI](http://localhost:5005/docs)
- [Open an issue on GitHub](https://github.com/tinyolly/tinyolly/issues)
- [Read the technical architecture](technical.md)
