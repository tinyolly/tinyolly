# Technical Details

<div align="center">
  <img src="../images/servicecatalog.png" alt="TinyOlly Architecture" width="600">
  <p><em>Service catalog showing RED metrics for all services</em></p>
</div>

---

## Architecture

```
Demo Frontend  ←→  Demo Backend (distributed tracing + auto-traffic)
        ↓                    ↓
   OTel Collector  ←─────────┘
        ↓
   TinyOlly OTLP Receiver (Async FastAPI, parses OTLP, stores in Redis)
        ↓
   Redis (30-minute TTL with cardinality protection)
        ↓
   TinyOlly UI & REST API (FastAPI + HTML + JavaScript)
```

---

## Data Storage

- **Format**: Full OpenTelemetry (OTEL) format for traces, logs, and metrics  
- **Redis**: All telemetry stored with 30-minute TTL (compressed with ZSTD + msgpack)  
- **Sorted Sets**: Time-series data indexed by timestamp  
- **Correlation**: Native trace-metric-log correlation via trace/span IDs  
- **Cardinality Protection**: Prevents metric explosion  
- **No Persistence**: Data vanishes after TTL (ephemeral dev tool)  

---

## OTLP Compatibility

TinyOlly is **fully OpenTelemetry-native**:  
- **Ingestion**: Accepts OTLP/gRPC (primary) and OTLP/HTTP  
- **Storage**: Stores traces, logs, and metrics in full OTEL format with resources, scopes, and attributes  
- **Correlation**: Native support for trace/span ID correlation across all telemetry types  
- **REST API**: Exposes OTEL-formatted JSON for programmatic access
