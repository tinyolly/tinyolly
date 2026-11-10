"""Size-bound trimming must keep data below the cap instead of wiping it.

Regression tests for: auto_vacuum was set after journal_mode=WAL (ignored on a new DB) and the size check
counted free pages, so after a trim the size never dropped and the cleanup deleted retained data every cycle.
"""
import os
import sqlite3
import time

import pytest

from tinyolly_common.storage_sqlite import StorageSQLite


def _span(i, pad):
    now = time.time_ns()
    return {
        "traceId": f"{i:032x}", "spanId": f"{i:016x}", "name": f"op{i}", "kind": 1,
        "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000),
        "attributes": [{"key": "pad", "value": {"stringValue": pad}}],
        "status": {}, "serviceName": "svc", "resource": {"service.name": "svc"}, "scope": {},
    }


def _auto_vacuum(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA auto_vacuum").fetchone()[0]
    finally:
        c.close()


@pytest.mark.asyncio
async def test_new_db_uses_incremental_auto_vacuum(tmp_path):
    s = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=60)
    await s._ensure_initialized()
    assert _auto_vacuum(s.db_path) == 2  # 2 = INCREMENTAL


@pytest.mark.asyncio
async def test_existing_db_is_migrated_without_losing_data(tmp_path):
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)                      # an old database: WAL, auto_vacuum = NONE
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE keepme(x)")
    c.execute("INSERT INTO keepme VALUES ('still here')")
    c.commit()
    c.close()
    assert _auto_vacuum(path) == 0

    s = StorageSQLite(db_path=path, ttl=60)
    await s._ensure_initialized()

    assert _auto_vacuum(path) == 2
    c = sqlite3.connect(path)
    assert c.execute("SELECT x FROM keepme").fetchone()[0] == "still here"
    c.close()


@pytest.mark.asyncio
async def test_db_size_excludes_free_pages(tmp_path):
    s = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=60)
    await s.store_spans([_span(i, os.urandom(2000).hex()) for i in range(300)])
    conn = await s._connect()
    try:
        full = await s._get_db_size(conn)
        await conn.execute("DELETE FROM spans")
        await conn.execute("DELETE FROM span_index")
        await conn.execute("DELETE FROM trace_spans")
        await conn.execute("DELETE FROM trace_index")
        await conn.execute("DELETE FROM traces")
        await conn.commit()
        after = await s._get_db_size(conn)
    finally:
        await conn.close()
    assert after < full * 0.5, f"size should drop after deleting rows (free pages excluded): {full} -> {after}"


@pytest.mark.asyncio
async def test_trim_keeps_recent_data_and_stops_below_the_cap(tmp_path):
    s = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=3600)
    await s._ensure_initialized()
    total = 500
    for batch in range(5):
        await s.store_spans([_span(batch * 100 + i, os.urandom(4000).hex()) for i in range(100)])

    conn = await s._connect()
    try:
        before = await s._get_db_size(conn)
    finally:
        await conn.close()
    s.max_db_size_bytes = int(before * 0.6)          # cap well below the current size => must trim
    high_water = int(s.max_db_size_bytes * 0.9)
    assert before > high_water, "test setup: DB should be over the high-water mark"

    await s._cleanup_expired_and_trim()

    conn = await s._connect()
    try:
        after = await s._get_db_size(conn)
        async with conn.execute("SELECT COUNT(*) FROM spans") as cur:
            remaining = (await cur.fetchone())[0]
    finally:
        await conn.close()

    assert after <= high_water, f"trim must get under the high-water mark: {after} > {high_water}"
    assert remaining >= total * 0.3, f"trim must keep a good share of the data, not wipe it: {remaining}/{total} spans left"
