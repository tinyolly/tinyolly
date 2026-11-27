"""
TinyOlly Storage Module (Async SQLite)
Handles all telemetry storage interactions using SQLite.

The class is assembled from mixins: spans, logs, metrics and services/graph live in storage_*.py.
"""


import asyncio
import base64
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import msgpack

from .storage_common import (
    COMPRESSION_THRESHOLD,
    MAX_DB_SIZE_MB,
    MAX_METRIC_CARDINALITY,
    MAX_PAGE_COUNT,
    SQLITE_DB_PATH,
    SQLITE_PAGE_SIZE,
    TTL_SECONDS,
    logger,
    zstd_compressor,
    zstd_decompressor,
)
from .storage_events import EventsMixin
from .storage_logs import LogsMixin
from .storage_metrics import MetricsMixin
from .storage_services import ServicesMixin
from .storage_spans import SpansMixin


class StorageSQLite(SpansMixin, LogsMixin, MetricsMixin, ServicesMixin, EventsMixin):
    """Async SQLite storage layer for OpenTelemetry data."""

    def __init__(
        self,
        db_path: str = SQLITE_DB_PATH,
        ttl: int = TTL_SECONDS,
        max_cardinality: int = MAX_METRIC_CARDINALITY,
        **_: Any,
    ):
        self.db_path = db_path
        self.ttl = ttl
        self.max_cardinality = max_cardinality
        self.max_db_size_bytes = MAX_DB_SIZE_MB * 1024 * 1024

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_client(self):
        """Compatibility method with Redis storage."""
        return None

    async def _connect(self, init: bool = False) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        try:
            conn.row_factory = aiosqlite.Row
            # busy_timeout FIRST: the UI and the OTLP receiver are separate processes opening the same file, and
            # switching to WAL needs a lock; without a timeout the second opener failed instantly with "database is locked".
            await conn.execute("PRAGMA busy_timeout=5000")
            # Both settings are stored in the file, so only initialization sets them: they need the write lock, and on
            # every connection they made reads and /health fail with "database is locked" under heavy ingest.
            # auto_vacuum only takes effect on a database that has no tables yet, and journal_mode=WAL creates the
            # file header, so it must be set BEFORE journal_mode. Existing databases are converted in
            # _ensure_initialized (one-time VACUUM).
            if init:
                await conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
                await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.execute("PRAGMA cache_size=-64000")
            await conn.execute(f"PRAGMA max_page_count={MAX_PAGE_COUNT}")
        except BaseException:
            await conn.close()
            raise
        return conn

    async def _migrate_auto_vacuum(self, conn: aiosqlite.Connection) -> None:
        """Convert a database created without auto_vacuum (older TinyOlly versions) to INCREMENTAL.

        Without this, deleting rows never returns pages to the file. Runs once; VACUUM rewrites the file
        (bounded by MAX_DB_SIZE_MB) and keeps all data.
        """
        async with conn.execute("PRAGMA auto_vacuum") as cur:
            row = await cur.fetchone()
        if row and int(row[0]) == 2:
            return
        async with conn.execute("SELECT COUNT(*) FROM sqlite_master") as cur:
            has_schema = bool((await cur.fetchone())[0])
        await conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        if has_schema:
            logger.info("Converting existing SQLite database to auto_vacuum=INCREMENTAL (one-time VACUUM)")
            await conn.execute("VACUUM")

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            conn = await self._connect(init=True)
            try:
                await self._migrate_auto_vacuum(conn)
                await conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS traces (
                        trace_id TEXT PRIMARY KEY,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data BLOB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS spans (
                        span_id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data BLOB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trace_spans (
                        trace_id TEXT NOT NULL,
                        span_id TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        PRIMARY KEY(trace_id, span_id)
                    );

                    CREATE TABLE IF NOT EXISTS trace_index (
                        trace_id TEXT PRIMARY KEY,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS span_index (
                        span_id TEXT PRIMARY KEY,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS logs (
                        log_id TEXT PRIMARY KEY,
                        trace_id TEXT,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data BLOB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trace_logs (
                        trace_id TEXT NOT NULL,
                        log_id TEXT NOT NULL,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        PRIMARY KEY(trace_id, log_id)
                    );

                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS metrics_names (
                        name TEXT PRIMARY KEY,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS metrics_meta (
                        name TEXT PRIMARY KEY,
                        data BLOB NOT NULL,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS metrics_resources (
                        name TEXT NOT NULL,
                        resource_json TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        UNIQUE(name, resource_json)
                    );

                    CREATE TABLE IF NOT EXISTS metrics_attributes (
                        name TEXT NOT NULL,
                        attr_json TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        UNIQUE(name, attr_json)
                    );

                    CREATE TABLE IF NOT EXISTS metrics_series (
                        name TEXT NOT NULL,
                        resource_hash TEXT NOT NULL,
                        attr_hash TEXT NOT NULL,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data BLOB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS metrics_exemplars (
                        name TEXT NOT NULL,
                        resource_hash TEXT NOT NULL,
                        attr_hash TEXT NOT NULL,
                        ts REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        data BLOB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS kv (
                        key TEXT PRIMARY KEY,
                        value BLOB NOT NULL,
                        expires_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS cardinality_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_trace_index_ts ON trace_index(ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_trace_index_exp ON trace_index(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_span_index_ts ON span_index(ts DESC);
                    -- the minute-by-minute expiry would otherwise scan every span while holding the write lock
                    CREATE INDEX IF NOT EXISTS idx_spans_exp ON spans(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_spans_exp ON trace_spans(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_span_index_exp ON span_index(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id, start_time);
                    CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_logs_trace ON logs(trace_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_logs_exp ON logs(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_logs_trace ON trace_logs(trace_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_metrics_series_name_ts ON metrics_series(name, ts);
                    CREATE INDEX IF NOT EXISTS idx_metrics_series_exp ON metrics_series(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_metrics_exemplars_name_ts ON metrics_exemplars(name, ts);
                    CREATE INDEX IF NOT EXISTS idx_metrics_exemplars_exp ON metrics_exemplars(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_metrics_resources_name ON metrics_resources(name);
                    CREATE INDEX IF NOT EXISTS idx_metrics_attributes_name ON metrics_attributes(name);
                    """
                )
                await conn.commit()
            finally:
                await conn.close()

            self._initialized = True
            self._ensure_cleanup_task()

    def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            return

        loop = asyncio.get_running_loop()
        self._cleanup_task = loop.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await self._cleanup_expired_and_trim()
            except Exception as e:
                if self._is_db_locked_error(e):
                    logger.debug(f"SQLite cleanup skipped due to lock contention: {e}")
                else:
                    logger.error(f"SQLite cleanup error: {e}", exc_info=True)
            await asyncio.sleep(60)

    @staticmethod
    def _is_db_locked_error(error: Exception) -> bool:
        return "database is locked" in str(error).lower()

    def _compress_for_storage(self, data: Dict[str, Any]) -> bytes:
        packed = msgpack.packb(data)
        if len(packed) > COMPRESSION_THRESHOLD:
            return b"ZSTD:" + zstd_compressor.compress(packed)
        return packed

    def _decompress_if_needed(self, data: bytes) -> Dict[str, Any]:
        if not data:
            return {}

        try:
            if isinstance(data, str) and data.startswith("ZLIB_B64:"):
                import zlib

                compressed = base64.b64decode(data[9:])
                decompressed = zlib.decompress(compressed)
                return json.loads(decompressed)

            if isinstance(data, (bytes, bytearray)) and data.startswith(b"ZSTD:"):
                decompressed = zstd_decompressor.decompress(data[5:])
                return msgpack.unpackb(decompressed)

            return msgpack.unpackb(data)
        except Exception as e:
            logger.error(f"SQLite deserialization error: {e}", exc_info=True)
            return {}

    def _normalize_datapoint(self, dp: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {
            "timestamp": dp["timestamp"],
            "value": float(dp["value"]) if dp["value"] is not None else None,
            "histogram": None,
            "summary": None,
        }

        if dp.get("histogram"):
            hist = dp["histogram"]
            normalized["histogram"] = {
                "count": int(hist["count"]) if isinstance(hist["count"], str) else hist["count"],
                "sum": float(hist["sum"]) if hist["sum"] is not None else 0,
                "bucketCounts": [int(c) if isinstance(c, str) else c for c in hist.get("bucketCounts", [])],
                "explicitBounds": [float(b) if b is not None else 0 for b in hist.get("explicitBounds", [])],
            }

        if dp.get("summary"):
            summ = dp["summary"]
            normalized["summary"] = {
                "count": int(summ["count"]) if isinstance(summ["count"], str) else summ["count"],
                "sum": float(summ["sum"]) if summ["sum"] is not None else 0,
                "quantileValues": [
                    {
                        "quantile": float(qv["quantile"]) if qv.get("quantile") is not None else 0,
                        "value": float(qv["value"]) if qv.get("value") is not None else 0,
                    }
                    for qv in summ.get("quantileValues", [])
                ],
            }

        return normalized

    async def _cleanup_expired_and_trim(self) -> None:
        await self._ensure_initialized()
        now = time.time()

        for attempt in range(3):
            async with self._write_lock:
                conn = await self._connect()
                try:
                    for table in (
                        "trace_logs",
                        "logs",
                        "events",
                        "trace_spans",
                        "spans",
                        "span_index",
                        "trace_index",
                        "traces",
                        "metrics_exemplars",
                        "metrics_series",
                        "metrics_resources",
                        "metrics_attributes",
                        "metrics_meta",
                        "metrics_names",
                        "kv",
                    ):
                        await conn.execute(f"DELETE FROM {table} WHERE expires_at <= ?", (now,))
                    await self._delete_orphans(conn)
                    await conn.commit()

                    # Trim oldest data when DB approaches size limit
                    await self._enforce_size_bounds(conn)
                    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    await conn.execute("PRAGMA incremental_vacuum(100)")
                    await conn.commit()
                    return
                except (aiosqlite.OperationalError, sqlite3.OperationalError) as e:
                    if not self._is_db_locked_error(e) or attempt == 2:
                        raise
                    await asyncio.sleep(0.1 * (attempt + 1))
                finally:
                    await conn.close()

    async def _delete_orphans(self, conn: aiosqlite.Connection) -> None:
        """Remove index rows whose spans are gone (trimmed by size or expired independently) and
        per-metric rows whose series are gone, so lists never point at data that no longer exists."""
        await conn.execute("DELETE FROM span_index WHERE span_id NOT IN (SELECT span_id FROM spans)")
        await conn.execute("DELETE FROM trace_spans WHERE span_id NOT IN (SELECT span_id FROM spans)")
        await conn.execute("DELETE FROM trace_index WHERE trace_id NOT IN (SELECT trace_id FROM trace_spans)")
        for table in ("metrics_meta", "metrics_resources", "metrics_attributes", "metrics_names"):
            await conn.execute(f"DELETE FROM {table} WHERE name NOT IN (SELECT DISTINCT name FROM metrics_series)")

    async def _retry_locked(self, op, attempts: int = 6):
        """Run a write transaction, retrying with backoff on "database is locked".

        The UI and the OTLP receiver are separate processes writing the same SQLite file, so a writer can be
        refused the lock (busy timeout exhausted, or an instant SQLITE_BUSY when WAL is being set up or a read
        transaction cannot upgrade). Dropping the batch on that error lost telemetry (e.g. a whole metrics
        export); retrying is safe because each attempt is one complete transaction.
        """
        for attempt in range(attempts):
            try:
                return await op()
            except (aiosqlite.OperationalError, sqlite3.OperationalError) as e:
                if not self._is_db_locked_error(e) or attempt == attempts - 1:
                    raise
                await asyncio.sleep(0.05 * 2 ** attempt)

    async def clear_all(self) -> Dict[str, int]:
        return await self._retry_locked(self._clear_all_once)

    async def _clear_all_once(self) -> Dict[str, int]:
        """Delete ALL stored telemetry (traces, spans, logs, metrics, caches). Testing/demo hook: gives
        automated runs and demos a clean slate without restarting the stack. Returns rows removed per table."""
        await self._ensure_initialized()
        removed: Dict[str, int] = {}
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN IMMEDIATE")
                for table in ("trace_logs", "logs", "events", "trace_spans", "spans", "span_index", "trace_index", "traces",
                              "metrics_exemplars", "metrics_series", "metrics_resources", "metrics_attributes",
                              "metrics_meta", "metrics_names", "kv", "cardinality_meta"):
                    cur = await conn.execute(f"DELETE FROM {table}")
                    removed[table] = max(cur.rowcount or 0, 0)
                await conn.commit()
                await conn.execute("PRAGMA incremental_vacuum")
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()
        self.get_metric_names.cache_clear()
        return removed

    async def close(self) -> None:
        """Stop the background cleanup task (call on application shutdown)."""
        task = self._cleanup_task
        self._cleanup_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _get_db_size(self, conn: aiosqlite.Connection) -> int:
        """Bytes of live data: pages in use, excluding free pages left behind by deletes.

        Counting free pages (plain page_count) made the size look unchanged after every trim, so the
        cleanup kept deleting retained data on each cycle.
        """
        async with conn.execute("PRAGMA page_count") as cur:
            row = await cur.fetchone()
            page_count = int(row[0]) if row else 0

        async with conn.execute("PRAGMA freelist_count") as cur:
            row = await cur.fetchone()
            freelist_count = int(row[0]) if row else 0
        page_count = max(page_count - freelist_count, 0)

        async with conn.execute("PRAGMA page_size") as cur:
            row = await cur.fetchone()
            page_size = int(row[0]) if row else SQLITE_PAGE_SIZE

        return page_count * page_size

    async def _trim_table_oldest(self, conn: aiosqlite.Connection, table: str, ts_col: str, batch_size: int = 1000) -> int:
        """Delete the oldest rows of one table: at most batch_size, and at most ~5% of the table per call.

        A fixed batch of 1000 emptied any table holding 1000 rows or fewer in a single step, wiping all
        retained data of that kind even when only a little space needed to be freed.
        """
        async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
            row_count = int((await cur.fetchone())[0])
        if row_count == 0:
            return 0
        limit = max(1, min(batch_size, row_count // 20))
        sql = f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY {ts_col} ASC LIMIT ?)"
        cur = await conn.execute(sql, (limit,))
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    async def _enforce_size_bounds(self, conn: aiosqlite.Connection) -> None:
        high_water = int(self.max_db_size_bytes * 0.9)
        low_water = int(self.max_db_size_bytes * 0.8)
        current_size = await self._get_db_size(conn)

        if current_size <= high_water:
            return

        trim_plan: List[Tuple[str, str]] = [
            ("metrics_series", "ts"),
            ("metrics_exemplars", "ts"),
            ("metrics_resources", "expires_at"),
            ("metrics_attributes", "expires_at"),
            ("metrics_meta", "expires_at"),
            ("metrics_names", "expires_at"),
            ("spans", "start_time"),
            ("span_index", "ts"),
            ("trace_spans", "start_time"),
            ("traces", "ts"),
            ("trace_index", "ts"),
            ("logs", "ts"),
            ("trace_logs", "ts"),
            ("kv", "expires_at"),
        ]

        attempts = 0
        while current_size > low_water and attempts < 30:
            deleted_any = False
            for table, ts_col in trim_plan:
                deleted = await self._trim_table_oldest(conn, table, ts_col)
                if deleted > 0:
                    deleted_any = True
                    await conn.commit()
                    current_size = await self._get_db_size(conn)
                    if current_size <= low_water:
                        return

            if not deleted_any:
                break

            attempts += 1

    async def is_connected(self) -> bool:
        try:
            await self._ensure_initialized()
            conn = await self._connect()
            try:
                async with conn.execute("SELECT 1") as cur:
                    await cur.fetchone()
                return True
            finally:
                await conn.close()
        except Exception:
            return False
