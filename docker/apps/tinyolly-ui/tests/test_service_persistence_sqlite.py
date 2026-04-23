import asyncio
import tempfile

import aiosqlite
import pytest
import pytest_asyncio

from tinyolly_common.storage_sqlite import StorageSQLite


@pytest_asyncio.fixture
async def sqlite_storage():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as handle:
        db_path = handle.name

    storage = StorageSQLite(db_path=db_path, ttl=60)
    try:
        yield storage
    finally:
        if storage._cleanup_task:
            storage._cleanup_task.cancel()
            try:
                await storage._cleanup_task
            except asyncio.CancelledError:
                pass


async def _expire_all_telemetry(storage: StorageSQLite) -> None:
    await storage._ensure_initialized()
    conn = await storage._connect()
    try:
        await conn.execute("UPDATE traces SET expires_at = 0")
        await conn.execute("UPDATE trace_index SET expires_at = 0")
        await conn.execute("UPDATE spans SET expires_at = 0")
        await conn.execute("UPDATE span_index SET expires_at = 0")
        await conn.execute("UPDATE trace_spans SET expires_at = 0")
        await conn.execute("UPDATE logs SET expires_at = 0")
        await conn.execute("UPDATE trace_logs SET expires_at = 0")
        await conn.execute("UPDATE metrics_names SET expires_at = 0")
        await conn.execute("UPDATE metrics_meta SET expires_at = 0")
        await conn.execute("UPDATE metrics_resources SET expires_at = 0")
        await conn.execute("UPDATE metrics_attributes SET expires_at = 0")
        await conn.execute("UPDATE metrics_series SET expires_at = 0")
        await conn.execute("UPDATE metrics_exemplars SET expires_at = 0")
        await conn.commit()
    finally:
        await conn.close()


async def _row_count(storage: StorageSQLite, table: str) -> int:
    await storage._ensure_initialized()
    conn = await storage._connect()
    try:
        async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        await conn.close()


async def _seed_service_data(storage: StorageSQLite) -> None:
    await storage.store_spans(
        [
            {
                "traceId": "trace-1",
                "spanId": "root-1",
                "parentSpanId": "",
                "name": "GET /checkout",
                "startTimeUnixNano": 1_700_000_000_000_000_000,
                "endTimeUnixNano": 1_700_000_000_200_000_000,
                "serviceName": "frontend",
                "attributes": [],
                "status": {},
            },
            {
                "traceId": "trace-1",
                "spanId": "child-1",
                "parentSpanId": "root-1",
                "name": "POST /reserve",
                "startTimeUnixNano": 1_700_000_000_020_000_000,
                "endTimeUnixNano": 1_700_000_000_120_000_000,
                "serviceName": "backend",
                "attributes": [],
                "status": {},
            },
        ]
    )

    await storage.store_logs(
        [
            {
                "log_id": "log-1",
                "timestamp": 1_700_000_000.1,
                "trace_id": "trace-1",
                "service_name": "frontend",
                "severity": "INFO",
                "message": "request complete",
                "attributes": {},
            }
        ]
    )

    await storage.store_metrics(
        [
            {
                "name": "demo.counter",
                "type": "sum",
                "unit": "1",
                "description": "demo",
                "temporality": "CUMULATIVE",
                "resource": {"service.name": "frontend"},
                "attributes": {"route": "/checkout"},
                "value": 1,
                "timestamp": 1_700_000_000.1,
                "exemplars": [],
            }
        ]
    )


@pytest.mark.asyncio
async def test_service_views_persist_until_refresh(sqlite_storage: StorageSQLite):
    await _seed_service_data(sqlite_storage)

    initial_catalog = await sqlite_storage.get_service_catalog()
    initial_graph = await sqlite_storage.get_service_graph()

    assert {service["name"] for service in initial_catalog} == {"frontend", "backend"}
    assert {node["id"] for node in initial_graph["nodes"]} == {"frontend", "backend"}
    assert any(edge["source"] == "frontend" and edge["target"] == "backend" for edge in initial_graph["edges"])

    await _expire_all_telemetry(sqlite_storage)
    await sqlite_storage._cleanup_expired_and_trim()

    persisted_catalog = await sqlite_storage.get_service_catalog()
    persisted_graph = await sqlite_storage.get_service_graph()

    assert {service["name"] for service in persisted_catalog} == {"frontend", "backend"}
    assert {node["id"] for node in persisted_graph["nodes"]} == {"frontend", "backend"}

    await sqlite_storage.reset_service_catalog()
    await sqlite_storage.reset_service_map()

    assert await sqlite_storage.get_service_catalog() == []
    assert await sqlite_storage.get_service_graph() == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_cleanup_removes_expired_telemetry_rows(sqlite_storage: StorageSQLite):
    await _seed_service_data(sqlite_storage)
    await _expire_all_telemetry(sqlite_storage)

    await sqlite_storage._cleanup_expired_and_trim()

    stats = await sqlite_storage.get_stats()
    assert stats["traces"] == 0
    assert stats["spans"] == 0
    assert stats["logs"] == 0
    assert stats["metrics"] == 0

    assert await _row_count(sqlite_storage, "trace_index") == 0
    assert await _row_count(sqlite_storage, "span_index") == 0
    assert await _row_count(sqlite_storage, "logs") == 0
    assert await _row_count(sqlite_storage, "metrics_series") == 0