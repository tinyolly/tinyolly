# TinyOlly Common

Shared Python package containing common utilities used across TinyOlly components.

## Components

- **storage_sqlite.py**: SQLite storage layer (default) with ZSTD compression and msgpack serialization
  - Handles traces, spans, logs, and metrics storage
  - Implements TTL-based automatic cleanup
  - WAL mode for concurrent read/write performance
  - Provides async/await interface via `aiosqlite`
- **storage.py**: Redis storage layer (archived—see [Redis Archive](../../docs/redis-archive.md))
  - Legacy backend, no longer the default

## Installation

This package is installed locally in editable mode during Docker build:

```bash
pip install -e /app/tinyolly-common
```

## Usage

```python
from tinyolly_common import Storage

storage = Storage()
await storage.store_traces(otlp_data)
```
