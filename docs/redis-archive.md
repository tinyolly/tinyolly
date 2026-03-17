# Redis Storage — Archive

!!! note "Archived"
    Redis was the original storage backend for TinyOlly. As of v3.0, **SQLite is the default and only actively maintained backend**. The Redis code (`storage.py`) is preserved in the repository for reference but is no longer used by default.

---

## Overview

TinyOlly originally used **Redis** as its storage backend for all OpenTelemetry telemetry data (traces, spans, logs, metrics). Redis was chosen for its:

- In-memory speed with native TTL support
- Sorted Sets for time-series indexing
- Simple key/value model that mapped well to ephemeral telemetry

---

## Why We Migrated to SQLite

| Concern | Redis | SQLite |
|---------|-------|--------|
| External process required | ✅ Yes (separate container/pod) | ❌ No (embedded) |
| Deployment complexity | Higher (extra service, port, auth) | Lower (single file) |
| Resource usage | ~128 MB baseline RAM | Near-zero at idle |
| Data size limit | `maxmemory` cap (eviction risk) | Configurable file size cap |
| WAL concurrent reads | No | ✅ Yes |
| Cold-start persistence | ❌ Volatile by default | ✅ File-based (TTL cleanup still applies) |
| Kubernetes footprint | Extra pod + Service | Shared PVC volume |

The primary driver was **deployment simplicity** — eliminating the Redis sidecar reduced the number of containers in every deployment (Docker and Kubernetes) and removed the external network dependency between services.

---

## Legacy Architecture (Redis)

```
OTLP Receiver ──► Redis :6579
                      ▲
TinyOlly UI   ──────►─┘
```

- **Data serialization**: msgpack + optional ZSTD compression (above 512-byte threshold)
- **Index structures**: Redis Sorted Sets keyed by timestamp for traces, spans, logs, and metric series
- **TTL**: Managed via Redis `EXPIRE` on individual keys (default 1800 s / 30 min)
- **Cardinality protection**: Enforced in application code by checking set cardinality before writes

### Key environment variables (Redis era)

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT_NUMBER` | `6579` | Redis port |
| `REDIS_TTL` | `1800` | Key TTL in seconds |
| `MAX_METRIC_CARDINALITY` | `1000` | Max unique metric names |
| `COMPRESSION_THRESHOLD_BYTES` | `512` | Compress payloads above this size |

### Redis index keys (legacy)

| Key pattern | Type | Used for |
|------------|------|----------|
| `trace_index` | Sorted Set | Trace IDs indexed by start time |
| `span_index` | Sorted Set | Span IDs indexed by start time |
| `log_index` | Sorted Set | Log record IDs indexed by timestamp |
| `trace:{id}` | Hash | Trace metadata |
| `spans:{trace_id}` | List | Span IDs belonging to a trace |
| `span:{id}` | Hash (compressed) | Full span data |
| `log:{id}` | Hash (compressed) | Full log record |
| `metric_series` | Set | All known metric series |

### Kubernetes resources (Redis era)

The file `k8s/redis.yaml` (and `k8s-core-only/redis.yaml`) deployed Redis as a Kubernetes Deployment + Service:

```yaml
# redis:7-alpine
# Port: 6579
# maxmemory: 256mb
# maxmemory-policy: allkeys-lru
```

These files are retained in the repository for historical reference but are **not applied** by the current deploy scripts.

---

## Current Storage (SQLite)

The equivalent concepts in the SQLite backend (`storage_sqlite.py`):

| Redis concept | SQLite equivalent |
|--------------|------------------|
| Sorted Set (time index) | `ORDER BY timestamp` on indexed column |
| Key TTL (`EXPIRE`) | Periodic background cleanup task |
| `maxmemory` cap | `MAX_PAGE_COUNT` PRAGMA (from `MAX_DB_SIZE_MB`) |
| Connection pooling | `aiosqlite` with WAL mode |
| Binary compression | Same: ZSTD + msgpack, same threshold |

### Current environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `sqlite` | Storage backend selector |
| `SQLITE_DB_PATH` | `/data/tinyolly.db` | Path to SQLite database file |
| `SQLITE_TTL_SECONDS` | `1800` | Data retention in seconds (alias: `REDIS_TTL`) |
| `MAX_DB_SIZE_MB` | `256` | Maximum SQLite file size |
| `MAX_METRIC_CARDINALITY` | `1000` | Max unique metric names |
| `COMPRESSION_THRESHOLD_BYTES` | `512` | Compress payloads above this size |

---

## Source Files

| File | Status | Notes |
|------|--------|-------|
| `docker/apps/tinyolly-common/tinyolly_common/storage.py` | **Archived** | Original Redis async client |
| `docker/apps/tinyolly-common/tinyolly_common/storage_sqlite.py` | **Active** | Current SQLite backend |
| `k8s/redis.yaml` | **Archived** | Kubernetes Redis Deployment + Service |
| `k8s-core-only/redis.yaml` | **Archived** | Core-only variant |
