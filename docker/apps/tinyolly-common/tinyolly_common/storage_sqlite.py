"""
TinyOlly Storage Module (Async SQLite)
Handles all telemetry storage interactions using SQLite.
"""

import asyncio
import base64
import json
import os
import sqlite3
import time
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import aiosqlite
import msgpack
import orjson
import zstandard as zstd
from async_lru import alru_cache

from .otlp_utils import parse_attributes, extract_resource_attributes, get_attr_value

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/tinyolly.db")
TTL_SECONDS = int(os.getenv("SQLITE_TTL_SECONDS", os.getenv("REDIS_TTL", "1800")))
MAX_METRIC_CARDINALITY = int(os.getenv("MAX_METRIC_CARDINALITY", "1000"))
COMPRESSION_THRESHOLD = int(os.getenv("COMPRESSION_THRESHOLD_BYTES", "512"))
SERVICE_GRAPH_CACHE_TTL = int(os.getenv("SERVICE_GRAPH_CACHE_TTL", "5"))
SERVICE_VIEW_CACHE_TTL = int(os.getenv("SERVICE_VIEW_CACHE_TTL", "20"))
SERVICE_SNAPSHOT_TTL_SECONDS = int(os.getenv("SERVICE_SNAPSHOT_TTL_SECONDS", "3600"))
SERVICE_RESET_TTL_SECONDS = int(os.getenv("SERVICE_RESET_TTL_SECONDS", "86400"))
MAX_DB_SIZE_MB = int(os.getenv("MAX_DB_SIZE_MB", "256"))
SQLITE_PAGE_SIZE = 4096
MAX_PAGE_COUNT = max((MAX_DB_SIZE_MB * 1024 * 1024) // SQLITE_PAGE_SIZE, 1)

zstd_compressor = zstd.ZstdCompressor(level=3)
zstd_decompressor = zstd.ZstdDecompressor()


class StorageSQLite:
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

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        await conn.execute(f"PRAGMA max_page_count={MAX_PAGE_COUNT}")
        return conn

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            conn = await self._connect()
            try:
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
                    CREATE INDEX IF NOT EXISTS idx_span_index_exp ON span_index(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id, start_time);
                    CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_logs_trace ON logs(trace_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_logs_exp ON logs(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_logs_trace ON trace_logs(trace_id, ts DESC);
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

    async def _get_db_size(self, conn: aiosqlite.Connection) -> int:
        async with conn.execute("PRAGMA page_count") as cur:
            row = await cur.fetchone()
            page_count = int(row[0]) if row else 0

        async with conn.execute("PRAGMA page_size") as cur:
            row = await cur.fetchone()
            page_size = int(row[0]) if row else SQLITE_PAGE_SIZE

        return page_count * page_size

    async def _trim_table_oldest(self, conn: aiosqlite.Connection, table: str, ts_col: str, batch_size: int = 1000) -> int:
        sql = f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY {ts_col} ASC LIMIT ?)"
        cur = await conn.execute(sql, (batch_size,))
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

    def parse_otlp_traces(self, otlp_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        spans: List[Dict[str, Any]] = []
        resource_spans_list = otlp_data.get("resourceSpans", [])

        for resource_spans in resource_spans_list:
            resource = resource_spans.get("resource", {})
            resource_attrs = extract_resource_attributes(resource)
            service_name = resource_attrs.get("service.name", "unknown")

            for scope_spans in resource_spans.get("scopeSpans", []):
                scope = scope_spans.get("scope", {})

                for span_data in scope_spans.get("spans", []):
                    trace_id_b64 = span_data.get("traceId", "")
                    span_id_b64 = span_data.get("spanId", "")
                    parent_span_id_b64 = span_data.get("parentSpanId", "")

                    if not trace_id_b64 or not span_id_b64:
                        continue

                    trace_id = base64.b64decode(trace_id_b64).hex() if trace_id_b64 else ""
                    span_id = base64.b64decode(span_id_b64).hex() if span_id_b64 else ""
                    parent_span_id = base64.b64decode(parent_span_id_b64).hex() if parent_span_id_b64 else ""

                    span_record = {
                        "traceId": trace_id,
                        "spanId": span_id,
                        "name": span_data.get("name", ""),
                        "kind": span_data.get("kind", 0),
                        "startTimeUnixNano": span_data.get("startTimeUnixNano", "0"),
                        "endTimeUnixNano": span_data.get("endTimeUnixNano", "0"),
                        "parentSpanId": parent_span_id,
                        "attributes": span_data.get("attributes", []),
                        "status": span_data.get("status", {}),
                        "serviceName": service_name,
                        "resource": resource_attrs,
                        "scope": {
                            "name": scope.get("name", ""),
                            "version": scope.get("version", ""),
                        },
                    }

                    spans.append(span_record)

        return spans

    async def store_traces(self, otlp_data: Dict[str, Any]) -> None:
        spans = self.parse_otlp_traces(otlp_data)
        if spans:
            await self.store_spans(spans)

    async def store_span(self, span: Dict[str, Any]) -> None:
        await self.store_spans([span])

    async def store_spans(self, spans: List[Dict[str, Any]]) -> None:
        if not spans:
            return

        await self._ensure_initialized()
        now = time.time()
        expires_at = now + self.ttl

        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN")
                for span in spans:
                    trace_id = span.get("traceId") or span.get("trace_id")
                    span_id = span.get("spanId") or span.get("span_id")
                    if not trace_id or not span_id:
                        continue

                    packed_data = self._compress_for_storage(span)
                    start_time = float(span.get("startTimeUnixNano", span.get("start_time", 0)) or 0)

                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO spans(span_id, trace_id, start_time, expires_at, data)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (span_id, trace_id, start_time, expires_at, packed_data),
                    )
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO trace_spans(trace_id, span_id, start_time, expires_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (trace_id, span_id, start_time, expires_at),
                    )
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO span_index(span_id, ts, expires_at)
                        VALUES (?, ?, ?)
                        """,
                        (span_id, now, expires_at),
                    )
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO trace_index(trace_id, ts, expires_at)
                        VALUES (?, ?, ?)
                        """,
                        (trace_id, now, expires_at),
                    )
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO traces(trace_id, ts, expires_at, data)
                        VALUES (?, ?, ?, ?)
                        """,
                        (trace_id, now, expires_at, packed_data),
                    )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()

    async def get_recent_traces(self, limit: int = 100, since_ts: Optional[float] = None) -> List[str]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if since_ts is None:
                sql = "SELECT trace_id FROM trace_index WHERE expires_at > ? ORDER BY ts DESC LIMIT ?"
                params = (now, limit)
            else:
                sql = "SELECT trace_id FROM trace_index WHERE expires_at > ? AND ts > ? ORDER BY ts DESC LIMIT ?"
                params = (now, since_ts, limit)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
            return [r[0] for r in rows]
        finally:
            await conn.close()

    async def get_recent_spans(self, limit: int = 100, since_ts: Optional[float] = None) -> List[str]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if since_ts is None:
                sql = "SELECT span_id FROM span_index WHERE expires_at > ? ORDER BY ts DESC LIMIT ?"
                params = (now, limit)
            else:
                sql = "SELECT span_id FROM span_index WHERE expires_at > ? AND ts > ? ORDER BY ts DESC LIMIT ?"
                params = (now, since_ts, limit)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
            return [r[0] for r in rows]
        finally:
            await conn.close()

    async def _get_recent_spans_data(self, limit: int, since_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if since_ts is None:
                sql = (
                    "SELECT s.data FROM span_index si "
                    "JOIN spans s ON s.span_id = si.span_id "
                    "WHERE si.expires_at > ? AND s.expires_at > ? "
                    "ORDER BY si.ts DESC LIMIT ?"
                )
                params = (now, now, limit)
            else:
                sql = (
                    "SELECT s.data FROM span_index si "
                    "JOIN spans s ON s.span_id = si.span_id "
                    "WHERE si.expires_at > ? AND s.expires_at > ? AND si.ts > ? "
                    "ORDER BY si.ts DESC LIMIT ?"
                )
                params = (now, now, since_ts, limit)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
            return [self._decompress_if_needed(row[0]) for row in rows]
        finally:
            await conn.close()

    async def _get_trace_spans_batch(self, trace_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        await self._ensure_initialized()
        if not trace_ids:
            return {}

        now = time.time()
        conn = await self._connect()
        spans_by_trace: Dict[str, List[Dict[str, Any]]] = {}
        try:
            chunk_size = 200
            for i in range(0, len(trace_ids), chunk_size):
                chunk = trace_ids[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                sql = (
                    "SELECT ts.trace_id, s.data "
                    "FROM trace_spans ts "
                    "JOIN spans s ON s.span_id = ts.span_id "
                    f"WHERE ts.expires_at > ? AND s.expires_at > ? AND ts.trace_id IN ({placeholders}) "
                    "ORDER BY ts.trace_id ASC, ts.start_time ASC"
                )
                params = [now, now, *chunk]
                async with conn.execute(sql, params) as cur:
                    rows = await cur.fetchall()

                for row in rows:
                    trace_id = row[0]
                    span = self._decompress_if_needed(row[1])
                    spans_by_trace.setdefault(trace_id, []).append(span)

            return spans_by_trace
        finally:
            await conn.close()

    async def get_span_details(self, span_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            async with conn.execute(
                "SELECT data FROM spans WHERE span_id = ? AND expires_at > ?",
                (span_id, now),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return None

            span = self._decompress_if_needed(row[0])
            method = get_attr_value(span, ["http.method", "http.request.method"])
            route = get_attr_value(span, ["http.route", "http.target", "url.path"])
            status_code = get_attr_value(span, ["http.status_code", "http.response.status_code"])
            server_name = get_attr_value(span, ["http.server_name", "net.host.name"])
            scheme = get_attr_value(span, ["http.scheme", "url.scheme"])
            host = get_attr_value(span, ["http.host", "net.host.name"])
            target = get_attr_value(span, ["http.target", "url.path"])
            url = get_attr_value(span, ["http.url", "url.full"])

            start_time = int(span.get("startTimeUnixNano", span.get("start_time", 0)))
            end_time = int(span.get("endTimeUnixNano", span.get("end_time", 0)))
            duration_ns = end_time - start_time if end_time > start_time else 0

            return {
                "span_id": span_id,
                "trace_id": span.get("traceId") or span.get("trace_id"),
                "name": span.get("name", "unknown"),
                "start_time": start_time,
                "duration_ms": duration_ns / 1_000_000,
                "method": method,
                "route": route,
                "status_code": status_code,
                "status": span.get("status", {}),
                "server_name": server_name,
                "scheme": scheme,
                "host": host,
                "target": target,
                "url": url,
                "service_name": span.get("serviceName", "unknown"),
            }
        except Exception as e:
            logger.error(f"Error getting span details: {e}", exc_info=True)
            return None
        finally:
            await conn.close()

    async def get_spans_details_batch(self, span_ids: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not span_ids:
            return results

        for span_id in span_ids:
            span = await self.get_span_details(span_id)
            if span:
                results.append(span)
        return results

    async def get_trace_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            async with conn.execute(
                """
                SELECT s.data
                FROM trace_spans ts
                JOIN spans s ON s.span_id = ts.span_id
                WHERE ts.trace_id = ? AND ts.expires_at > ? AND s.expires_at > ?
                ORDER BY ts.start_time ASC
                """,
                (trace_id, now, now),
            ) as cur:
                rows = await cur.fetchall()

            return [self._decompress_if_needed(row[0]) for row in rows]
        except Exception as e:
            logger.error(f"Error getting trace spans: {e}", exc_info=True)
            return []
        finally:
            await conn.close()

    async def get_trace_summary(self, trace_id: str) -> Optional[Dict[str, Any]]:
        spans = await self.get_trace_spans(trace_id)
        if not spans:
            return None

        start_times = [int(s.get("startTimeUnixNano", s.get("start_time", 0))) for s in spans]
        end_times = [int(s.get("endTimeUnixNano", s.get("end_time", 0))) for s in spans]
        min_start = min(start_times) if start_times else 0
        max_end = max(end_times) if end_times else 0
        duration_ns = max_end - min_start

        root_span = next((s for s in spans if not s.get("parentSpanId") and not s.get("parent_span_id")), spans[0])

        root_span_method = get_attr_value(root_span, ["http.method", "http.request.method"])
        root_span_route = get_attr_value(root_span, ["http.route", "http.target", "url.path"])
        root_span_status_code = get_attr_value(root_span, ["http.status_code", "http.response.status_code"])
        root_span_server_name = get_attr_value(root_span, ["http.server_name", "net.host.name"])
        root_span_scheme = get_attr_value(root_span, ["http.scheme", "url.scheme"])
        root_span_host = get_attr_value(root_span, ["http.host", "net.host.name"])
        root_span_target = get_attr_value(root_span, ["http.target", "url.path"])
        root_span_url = get_attr_value(root_span, ["http.url", "url.full"])
        root_span_service_name = root_span.get("serviceName", "unknown")

        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "duration_ms": duration_ns / 1_000_000 if duration_ns else 0,
            "start_time": min_start,
            "root_span_name": root_span.get("name", "unknown"),
            "root_span_method": root_span_method,
            "root_span_route": root_span_route,
            "root_span_status_code": root_span_status_code,
            "root_span_status": root_span.get("status", {}),
            "root_span_server_name": root_span_server_name,
            "root_span_scheme": root_span_scheme,
            "root_span_host": root_span_host,
            "root_span_target": root_span_target,
            "root_span_url": root_span_url,
            "service_name": root_span_service_name,
        }

    def parse_otlp_logs(self, otlp_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        logs: List[Dict[str, Any]] = []

        resource_logs_list = otlp_data.get("resourceLogs", [])
        for resource_logs in resource_logs_list:
            resource = resource_logs.get("resource", {})
            resource_attrs = extract_resource_attributes(resource)
            service_name = resource_attrs.get("service.name", "unknown")

            for scope_logs in resource_logs.get("scopeLogs", []):
                scope = scope_logs.get("scope", {})

                for log_record in scope_logs.get("logRecords", []):
                    time_unix_nano = log_record.get("timeUnixNano", "0")
                    if isinstance(time_unix_nano, str):
                        time_unix_nano = int(time_unix_nano)
                    timestamp = time_unix_nano / 1_000_000_000 if time_unix_nano else time.time()

                    trace_id_b64 = log_record.get("traceId", "")
                    span_id_b64 = log_record.get("spanId", "")
                    trace_id = base64.b64decode(trace_id_b64).hex() if trace_id_b64 else ""
                    span_id = base64.b64decode(span_id_b64).hex() if span_id_b64 else ""

                    body = log_record.get("body", {})
                    message = body.get("stringValue", "") if isinstance(body, dict) else str(body)
                    severity = log_record.get("severityText", "INFO")

                    logs.append(
                        {
                            "timestamp": timestamp,
                            "severity": severity,
                            "message": message,
                            "trace_id": trace_id,
                            "span_id": span_id,
                            "service_name": service_name,
                            "attributes": parse_attributes(log_record.get("attributes", [])),
                            "resource": resource_attrs,
                            "scope": {
                                "name": scope.get("name", ""),
                                "version": scope.get("version", ""),
                            },
                        }
                    )

        return logs

    async def store_logs_otlp(self, otlp_data: Dict[str, Any]) -> None:
        logs = self.parse_otlp_logs(otlp_data)
        if logs:
            await self.store_logs(logs)

    async def store_log(self, log: Dict[str, Any]) -> None:
        await self.store_logs([log])

    async def store_logs(self, logs: List[Dict[str, Any]]) -> None:
        if not logs:
            return

        await self._ensure_initialized()
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN")
                now = time.time()
                expires_at = now + self.ttl

                for log in logs:
                    if "log_id" not in log:
                        log["log_id"] = str(uuid.uuid4())

                    log_id = log["log_id"]
                    timestamp = float(log.get("timestamp", now))
                    log["timestamp"] = timestamp
                    trace_id = log.get("trace_id") or log.get("traceId")
                    packed_data = self._compress_for_storage(log)

                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO logs(log_id, trace_id, ts, expires_at, data)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (log_id, trace_id, timestamp, expires_at, packed_data),
                    )

                    if trace_id:
                        await conn.execute(
                            """
                            INSERT OR REPLACE INTO trace_logs(trace_id, log_id, ts, expires_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (trace_id, log_id, timestamp, expires_at),
                        )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()

    async def get_logs(self, trace_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if trace_id:
                sql = (
                    "SELECT l.data FROM trace_logs tl "
                    "JOIN logs l ON l.log_id = tl.log_id "
                    "WHERE tl.trace_id = ? AND tl.expires_at > ? AND l.expires_at > ? "
                    "ORDER BY tl.ts DESC LIMIT ?"
                )
                params = (trace_id, now, now, limit)
            else:
                sql = "SELECT data FROM logs WHERE expires_at > ? ORDER BY ts DESC LIMIT ?"
                params = (now, limit)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()

            return [self._decompress_if_needed(row[0]) for row in rows]
        except Exception as e:
            logger.error(f"Error getting logs: {e}", exc_info=True)
            return []
        finally:
            await conn.close()

    def _hash_dict(self, d: Dict[str, Any]) -> str:
        import hashlib

        sorted_items = sorted(d.items())
        s = json.dumps(sorted_items, sort_keys=True)
        return hashlib.md5(s.encode()).hexdigest()[:8]

    def parse_otlp_metrics(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        datapoints: List[Dict[str, Any]] = []

        resource_metrics = data.get("resourceMetrics", data.get("resource_metrics", []))
        for resource_metric in resource_metrics:
            resource = resource_metric.get("resource", {})
            resource_attrs = extract_resource_attributes(resource)
            scope_metrics = resource_metric.get("scopeMetrics", [])

            for scope_metric in scope_metrics:
                metrics = scope_metric.get("metrics", [])

                for metric in metrics:
                    name = metric.get("name")
                    unit = metric.get("unit", "")
                    description = metric.get("description", "")
                    if not name:
                        continue

                    metric_type = "unknown"
                    metric_datapoints: List[Dict[str, Any]] = []
                    temporality = None

                    if "gauge" in metric:
                        metric_type = "gauge"
                        metric_datapoints = metric["gauge"].get("dataPoints", [])
                    elif "sum" in metric:
                        metric_type = "sum"
                        sum_data = metric["sum"]
                        metric_datapoints = sum_data.get("dataPoints", [])
                        temporality = sum_data.get("aggregationTemporality", "CUMULATIVE")
                    elif "histogram" in metric:
                        metric_type = "histogram"
                        histogram = metric["histogram"]
                        metric_datapoints = histogram.get("dataPoints", [])
                        temporality = histogram.get("aggregationTemporality", "CUMULATIVE")
                    elif "summary" in metric:
                        metric_type = "summary"
                        metric_datapoints = metric["summary"].get("dataPoints", [])

                    for dp in metric_datapoints:
                        dp_attrs = parse_attributes(dp.get("attributes", []))

                        time_unix_nano = dp.get("timeUnixNano", 0)
                        if isinstance(time_unix_nano, str):
                            time_unix_nano = int(time_unix_nano)
                        timestamp = time_unix_nano / 1_000_000_000 if time_unix_nano else time.time()

                        value = None
                        histogram_data = None
                        summary_data = None

                        if metric_type in ("gauge", "sum"):
                            if "asInt" in dp:
                                value = dp["asInt"]
                            elif "asDouble" in dp:
                                value = dp["asDouble"]
                        elif metric_type == "histogram":
                            value = dp.get("sum", 0)
                            histogram_data = {
                                "count": dp.get("count", 0),
                                "sum": dp.get("sum", 0),
                                "bucketCounts": dp.get("bucketCounts", []),
                                "explicitBounds": dp.get("explicitBounds", []),
                            }
                        elif metric_type == "summary":
                            value = dp.get("sum", 0)
                            summary_data = {
                                "count": dp.get("count", 0),
                                "sum": dp.get("sum", 0),
                                "quantileValues": dp.get("quantileValues", []),
                            }

                        exemplars = []
                        for ex in dp.get("exemplars", []):
                            ex_time_nano = ex.get("timeUnixNano", 0)
                            if isinstance(ex_time_nano, str):
                                ex_time_nano = int(ex_time_nano)
                            ex_timestamp = ex_time_nano / 1_000_000_000 if ex_time_nano else timestamp

                            ex_value = None
                            if "asInt" in ex:
                                ex_value = ex["asInt"]
                            elif "asDouble" in ex:
                                ex_value = ex["asDouble"]

                            trace_id = ex.get("traceId", "")
                            span_id = ex.get("spanId", "")
                            if isinstance(trace_id, bytes):
                                trace_id = trace_id.hex()
                            if isinstance(span_id, bytes):
                                span_id = span_id.hex()

                            exemplars.append(
                                {
                                    "timestamp": ex_timestamp,
                                    "value": ex_value,
                                    "traceId": trace_id,
                                    "spanId": span_id,
                                    "filteredAttributes": parse_attributes(ex.get("filteredAttributes", [])),
                                }
                            )

                        datapoints.append(
                            {
                                "name": name,
                                "type": metric_type,
                                "unit": unit,
                                "description": description,
                                "temporality": temporality,
                                "resource": resource_attrs,
                                "attributes": dp_attrs,
                                "timestamp": timestamp,
                                "value": value,
                                "histogram": histogram_data,
                                "summary": summary_data,
                                "exemplars": exemplars,
                            }
                        )

        return datapoints

    async def store_metric_datapoint(
        self,
        name: str,
        metric_type: str,
        unit: str,
        description: str,
        temporality: Optional[str],
        resource: Dict[str, Any],
        attributes: Dict[str, Any],
        value: Any,
        timestamp: float,
        histogram: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        exemplars: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        await self._ensure_initialized()
        now = time.time()
        expires_at = now + self.ttl

        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN")
                resource_hash = self._hash_dict(resource)
                attr_hash = self._hash_dict(attributes)

                await conn.execute(
                    "INSERT OR REPLACE INTO metrics_names(name, expires_at) VALUES (?, ?)",
                    (name, expires_at),
                )

                meta_data = {
                    "type": metric_type,
                    "unit": unit,
                    "description": description,
                    "temporality": temporality or "N/A",
                }
                await conn.execute(
                    "INSERT OR REPLACE INTO metrics_meta(name, data, expires_at) VALUES (?, ?, ?)",
                    (name, orjson.dumps(meta_data), expires_at),
                )

                await conn.execute(
                    """
                    INSERT INTO metrics_resources(name, resource_json, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name, resource_json) DO UPDATE SET expires_at=excluded.expires_at
                    """,
                    (name, orjson.dumps(resource).decode("utf-8"), expires_at),
                )

                if attributes:
                    await conn.execute(
                        """
                        INSERT INTO metrics_attributes(name, attr_json, expires_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(name, attr_json) DO UPDATE SET expires_at=excluded.expires_at
                        """,
                        (name, orjson.dumps(attributes, option=orjson.OPT_SORT_KEYS).decode("utf-8"), expires_at),
                    )

                datapoint_data = {
                    "resource": resource,
                    "attributes": attributes,
                    "value": value,
                    "timestamp": timestamp,
                    "histogram": histogram,
                    "summary": summary,
                }

                await conn.execute(
                    """
                    INSERT INTO metrics_series(name, resource_hash, attr_hash, ts, expires_at, data)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, resource_hash, attr_hash, timestamp, expires_at, self._compress_for_storage(datapoint_data)),
                )

                if exemplars:
                    for ex in exemplars:
                        await conn.execute(
                            """
                            INSERT INTO metrics_exemplars(name, resource_hash, attr_hash, ts, expires_at, data)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                name,
                                resource_hash,
                                attr_hash,
                                float(ex.get("timestamp", timestamp)),
                                expires_at,
                                self._compress_for_storage(ex),
                            ),
                        )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()

    async def store_metric(self, metric: Dict[str, Any]) -> None:
        await self.store_metrics([metric])

    async def store_metrics(self, metrics: Any) -> None:
        if not metrics:
            return

        if isinstance(metrics, dict) and ("resourceMetrics" in metrics or "resource_metrics" in metrics):
            datapoints = self.parse_otlp_metrics(metrics)
            for dp in datapoints:
                await self.store_metric_datapoint(
                    name=dp["name"],
                    metric_type=dp["type"],
                    unit=dp["unit"],
                    description=dp["description"],
                    temporality=dp["temporality"],
                    resource=dp["resource"],
                    attributes=dp["attributes"],
                    value=dp["value"],
                    timestamp=dp["timestamp"],
                    histogram=dp["histogram"],
                    summary=dp["summary"],
                    exemplars=dp["exemplars"],
                )
            return

        legacy_metrics = metrics if isinstance(metrics, list) else [metrics]
        for metric in legacy_metrics:
            name = metric.get("name")
            if not name:
                continue

            await self.store_metric_datapoint(
                name=name,
                metric_type=metric.get("type", "unknown"),
                unit=metric.get("unit", ""),
                description=metric.get("description", ""),
                temporality=metric.get("temporality", "N/A"),
                resource=metric.get("resource", {}),
                attributes=metric.get("attributes", {}),
                value=metric.get("value"),
                timestamp=float(metric.get("timestamp", time.time())),
                histogram=metric.get("histogram"),
                summary=metric.get("summary"),
                exemplars=metric.get("exemplars", []),
            )

    @alru_cache(maxsize=1, ttl=10)
    async def get_metric_names(self, limit: Optional[int] = None) -> List[str]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if limit and limit > 0:
                sql = "SELECT name FROM metrics_names WHERE expires_at > ? ORDER BY name ASC LIMIT ?"
                params = (now, limit)
            else:
                sql = "SELECT name FROM metrics_names WHERE expires_at > ? ORDER BY name ASC"
                params = (now,)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
            return [row[0] for row in rows]
        finally:
            await conn.close()

    async def get_metric_metadata(self, name: str) -> Dict[str, Any]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            async with conn.execute(
                "SELECT data FROM metrics_meta WHERE name = ? AND expires_at > ?",
                (name, now),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return {"type": "unknown", "unit": "", "description": "", "temporality": "N/A"}

            return orjson.loads(row[0])
        except Exception as e:
            logger.error(f"Error getting metric metadata: {e}", exc_info=True)
            return {"type": "unknown", "unit": "", "description": "", "temporality": "N/A"}
        finally:
            await conn.close()

    async def get_all_resources(self, metric_name: str) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            async with conn.execute(
                "SELECT resource_json FROM metrics_resources WHERE name = ? AND expires_at > ?",
                (metric_name, now),
            ) as cur:
                rows = await cur.fetchall()
            return [orjson.loads(row[0]) for row in rows]
        except Exception as e:
            logger.error(f"Error getting resources: {e}", exc_info=True)
            return []
        finally:
            await conn.close()

    async def get_all_attributes(self, metric_name: str, resource_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if not resource_filter:
                async with conn.execute(
                    "SELECT attr_json FROM metrics_attributes WHERE name = ? AND expires_at > ?",
                    (metric_name, now),
                ) as cur:
                    rows = await cur.fetchall()
                return [orjson.loads(row[0]) for row in rows]

            async with conn.execute(
                "SELECT data FROM metrics_series WHERE name = ? AND expires_at > ?",
                (metric_name, now),
            ) as cur:
                rows = await cur.fetchall()

            attrs_set = set()
            for row in rows:
                dp = self._decompress_if_needed(row[0])
                dp_resource = dp.get("resource", {})
                if all(dp_resource.get(k) == v for k, v in resource_filter.items()):
                    attrs_set.add(orjson.dumps(dp.get("attributes", {}), option=orjson.OPT_SORT_KEYS))

            return [orjson.loads(a) for a in attrs_set]
        except Exception as e:
            logger.error(f"Error getting attributes: {e}", exc_info=True)
            return []
        finally:
            await conn.close()

    async def get_metric_series(
        self,
        name: str,
        resource_filter: Optional[Dict[str, Any]] = None,
        attr_filter: Optional[Dict[str, Any]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        await self._ensure_initialized()

        if start_time is None:
            start_time = time.time() - 3600
        if end_time is None:
            end_time = time.time()

        conn = await self._connect()
        try:
            now = time.time()
            async with conn.execute(
                """
                SELECT resource_hash, attr_hash, ts, data
                FROM metrics_series
                WHERE name = ? AND expires_at > ? AND ts BETWEEN ? AND ?
                ORDER BY ts ASC
                """,
                (name, now, start_time, end_time),
            ) as cur:
                rows = await cur.fetchall()

            grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for row in rows:
                resource_hash = row[0]
                attr_hash = row[1]
                dp = self._decompress_if_needed(row[3])

                dp_resource = dp.get("resource", {})
                dp_attributes = dp.get("attributes", {})

                if resource_filter and not all(dp_resource.get(k) == v for k, v in resource_filter.items()):
                    continue
                if attr_filter and not all(dp_attributes.get(k) == v for k, v in attr_filter.items()):
                    continue

                key = (resource_hash, attr_hash)
                if key not in grouped:
                    grouped[key] = {
                        "resource": dp_resource,
                        "attributes": dp_attributes,
                        "datapoints": [],
                        "exemplars": [],
                    }

                grouped[key]["datapoints"].append(
                    self._normalize_datapoint(
                        {
                            "timestamp": dp.get("timestamp", row[2]),
                            "value": dp.get("value"),
                            "histogram": dp.get("histogram"),
                            "summary": dp.get("summary"),
                        }
                    )
                )

            for resource_hash, attr_hash in grouped.keys():
                async with conn.execute(
                    """
                    SELECT data
                    FROM metrics_exemplars
                    WHERE name = ? AND resource_hash = ? AND attr_hash = ?
                                            AND expires_at > ?
                      AND ts BETWEEN ? AND ?
                    ORDER BY ts ASC
                    """,
                                        (name, resource_hash, attr_hash, now, start_time, end_time),
                ) as cur:
                    ex_rows = await cur.fetchall()
                grouped[(resource_hash, attr_hash)]["exemplars"] = [
                    self._decompress_if_needed(r[0]) for r in ex_rows
                ]

            return list(grouped.values())
        except Exception as e:
            logger.error(f"Error getting metric series: {e}", exc_info=True)
            return []
        finally:
            await conn.close()

    async def get_cardinality_stats(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            async with conn.execute("SELECT COUNT(*) FROM metrics_names WHERE expires_at > ?", (now,)) as cur:
                row = await cur.fetchone()
                current = int(row[0]) if row else 0

            async with conn.execute("SELECT value FROM cardinality_meta WHERE key='metric_dropped_count'") as cur:
                dropped_row = await cur.fetchone()

            async with conn.execute("SELECT value FROM cardinality_meta WHERE key='metric_dropped_names'") as cur:
                dropped_names_row = await cur.fetchone()

            dropped_names = []
            if dropped_names_row and dropped_names_row[0]:
                try:
                    dropped_names = json.loads(dropped_names_row[0])
                except Exception:
                    dropped_names = []

            return {
                "current": current,
                "max": self.max_cardinality,
                "dropped_count": int(dropped_row[0]) if dropped_row and dropped_row[0] else 0,
                "dropped_names": dropped_names,
            }
        finally:
            await conn.close()

    async def get_metric_data(self, name: str, start_time: float, end_time: float) -> List[Dict[str, Any]]:
        series = await self.get_metric_series(name, None, None, start_time, end_time)
        data: List[Dict[str, Any]] = []
        for s in series:
            data.extend(s.get("datapoints", []))
        return data

    async def _cache_get_json(self, key: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        conn = await self._connect()
        try:
            now = time.time()
            async with conn.execute(
                "SELECT value FROM kv WHERE key=? AND expires_at > ?",
                (key, now),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            return orjson.loads(row[0])
        except Exception:
            return None
        finally:
            await conn.close()

    async def _cache_set_json(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        await self._ensure_initialized()
        async with self._write_lock:
            for attempt in range(3):
                conn = await self._connect()
                try:
                    expires_at = time.time() + ttl_seconds
                    await conn.execute(
                        "INSERT OR REPLACE INTO kv(key, value, expires_at) VALUES (?, ?, ?)",
                        (key, orjson.dumps(value), expires_at),
                    )
                    await conn.commit()
                    return
                except aiosqlite.OperationalError as e:
                    if not self._is_db_locked_error(e) or attempt == 2:
                        logger.warning(f"SQLite cache write skipped for key={key}: {e}")
                        return
                    await asyncio.sleep(0.1 * (attempt + 1))
                finally:
                    await conn.close()

    async def _cache_set_json_safe(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        try:
            await self._cache_set_json(key, value, ttl_seconds)
        except Exception as e:
            logger.warning(f"SQLite cache write failed for key={key}: {e}")

    async def _cache_delete(self, key: str) -> None:
        await self._ensure_initialized()
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                await conn.commit()
            finally:
                await conn.close()

    async def _cache_delete_like(self, pattern: str) -> None:
        await self._ensure_initialized()
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("DELETE FROM kv WHERE key LIKE ?", (pattern,))
                await conn.commit()
            finally:
                await conn.close()

    def _service_cache_key(self, view: str) -> str:
        return f"service_view_cache_v1:{view}"

    def _service_snapshot_key(self, view: str) -> str:
        return f"service_view_snapshot_v1:{view}"

    def _service_reset_key(self, view: str) -> str:
        return f"service_view_reset_v1:{view}"

    async def _get_service_reset_ts(self, view: str) -> float:
        payload = await self._cache_get_json(self._service_reset_key(view))
        if not payload:
            return 0.0
        return float(payload.get("reset_at", 0.0) or 0.0)

    async def _set_service_reset_ts(self, view: str, reset_at: float) -> None:
        await self._cache_set_json(
            self._service_reset_key(view),
            {"reset_at": reset_at},
            SERVICE_RESET_TTL_SECONDS,
        )

    async def reset_service_map(self) -> None:
        await self._set_service_reset_ts("map", time.time())
        await self._cache_delete_like("service_graph_cache_v%")
        await self._cache_delete(self._service_snapshot_key("map"))

    async def reset_service_catalog(self) -> None:
        await self._set_service_reset_ts("catalog", time.time())
        await self._cache_delete(self._service_cache_key("catalog"))
        await self._cache_delete(self._service_snapshot_key("catalog"))

    async def get_service_graph(self, limit: int = 500) -> Dict[str, Any]:
        cache_key = f"service_graph_cache_v3:{limit}"
        snapshot_key = self._service_snapshot_key("map")
        reset_at = await self._get_service_reset_ts("map")
        trace_ids = await self.get_recent_traces(limit, since_ts=reset_at)

        if not trace_ids:
            snapshot = await self._cache_get_json(snapshot_key)
            return snapshot or {"nodes": [], "edges": []}

        cached_graph = await self._cache_get_json(cache_key)
        if cached_graph:
            return cached_graph

        catalog_services = await self.get_service_catalog()
        service_metrics = {s["name"]: s for s in catalog_services}

        nodes: Dict[str, Dict[str, Any]] = {}
        for s in catalog_services:
            nodes[s["name"]] = {"type": "service", "metrics": s}

        edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
        spans_by_trace = await self._get_trace_spans_batch(trace_ids)

        for trace_id in trace_ids:
            spans = spans_by_trace.get(trace_id, [])
            if not spans:
                continue

            span_map = {s.get("spanId", s.get("span_id")): s for s in spans}

            for span in spans:
                service = span.get("serviceName", "unknown")
                if service and service != "unknown" and service not in nodes:
                    nodes[service] = {"type": "service", "metrics": service_metrics.get(service, {})}

                start = int(span.get("startTimeUnixNano", span.get("start_time", 0)))
                end = int(span.get("endTimeUnixNano", span.get("end_time", 0)))
                duration_ms = (end - start) / 1_000_000 if end > start else 0

                target_node = None
                node_type = None

                db_system = get_attr_value(span, ["db.system"])
                if db_system:
                    db_name = get_attr_value(span, ["db.name"]) or db_system
                    target_node = db_name
                    node_type = "database"

                messaging_system = get_attr_value(span, ["messaging.system"])
                if messaging_system:
                    dest = get_attr_value(span, ["messaging.destination"]) or messaging_system
                    target_node = dest
                    node_type = "messaging"

                if target_node:
                    if target_node not in nodes:
                        nodes[target_node] = {"type": node_type, "metrics": {}}
                    key = (service, target_node)
                    if key not in edges:
                        edges[key] = {"count": 0, "durations": []}
                    edges[key]["count"] += 1
                    edges[key]["durations"].append(duration_ms)

                parent_id = span.get("parentSpanId", span.get("parent_span_id"))
                if parent_id and parent_id in span_map:
                    parent = span_map[parent_id]
                    parent_service = parent.get("serviceName", "unknown")
                    if parent_service != service and parent_service != "unknown" and service != "unknown":
                        key = (parent_service, service)
                        if key not in edges:
                            edges[key] = {"count": 0, "durations": []}
                        edges[key]["count"] += 1
                        edges[key]["durations"].append(duration_ms)

        graph_nodes = [
            {"id": name, "label": name, "type": data.get("type", "service"), "metrics": data.get("metrics", {})}
            for name, data in nodes.items()
        ]

        graph_edges = []
        for (source, target), data in edges.items():
            durations = sorted(data["durations"])
            p95 = 0
            if durations:
                idx = int(len(durations) * 0.95)
                idx = min(idx, len(durations) - 1)
                p95 = durations[idx]

            graph_edges.append(
                {
                    "source": source,
                    "target": target,
                    "value": data["count"],
                    "p95": round(p95, 2),
                    "req_rate": round(data["count"] / 60, 2),
                }
            )

        result = {"nodes": graph_nodes, "edges": graph_edges}
        await self._cache_set_json_safe(snapshot_key, result, SERVICE_SNAPSHOT_TTL_SECONDS)
        await self._cache_set_json_safe(cache_key, result, SERVICE_VIEW_CACHE_TTL)
        return result

    async def get_service_catalog(self) -> List[Dict[str, Any]]:
        cache_key = self._service_cache_key("catalog")
        snapshot_key = self._service_snapshot_key("catalog")
        reset_at = await self._get_service_reset_ts("catalog")
        spans = await self._get_recent_spans_data(10000, since_ts=reset_at)

        if not spans:
            snapshot = await self._cache_get_json(snapshot_key)
            return snapshot or []

        cached_catalog = await self._cache_get_json(cache_key)
        if cached_catalog:
            return cached_catalog

        services: Dict[str, Dict[str, Any]] = {}

        for span in spans:
            service_name = span.get("serviceName") or span.get("service_name") or "unknown"
            trace_id = span.get("traceId") or span.get("trace_id")
            start_time = int(span.get("startTimeUnixNano", span.get("start_time", 0)) or 0)
            end_time = int(span.get("endTimeUnixNano", span.get("end_time", 0)) or 0)
            duration_ms = (end_time - start_time) / 1_000_000 if end_time > start_time else 0.0

            status_obj = span.get("status", {}) or {}
            status_code = status_obj.get("code") if isinstance(status_obj, dict) else None
            is_error = status_code == 2

            if service_name not in services:
                services[service_name] = {
                    "name": service_name,
                    "span_count": 0,
                    "trace_ids": set(),
                    "first_seen": start_time,
                    "last_seen": start_time,
                    "durations": [],
                    "error_count": 0,
                }

            services[service_name]["span_count"] += 1
            services[service_name]["trace_ids"].add(trace_id)
            services[service_name]["first_seen"] = min(services[service_name]["first_seen"], start_time)
            services[service_name]["last_seen"] = max(services[service_name]["last_seen"], start_time)
            services[service_name]["durations"].append(duration_ms)
            if is_error:
                services[service_name]["error_count"] += 1

        result = []
        for service_name, data in services.items():
            durations = sorted(data["durations"])
            p50 = None
            p95 = None
            p99 = None
            if durations:
                p50 = round(durations[int((len(durations) - 1) * 0.50)], 2)
                p95 = round(durations[int((len(durations) - 1) * 0.95)], 2)
                p99 = round(durations[int((len(durations) - 1) * 0.99)], 2)

            span_count = data["span_count"]
            error_count = data["error_count"]
            service_info = {
                "name": data["name"],
                "span_count": span_count,
                "trace_count": len(data["trace_ids"]),
                "first_seen": data["first_seen"],
                "last_seen": data["last_seen"],
                "rate": max(1, round(span_count / 300)) if span_count > 0 else 0,
                "error_rate": round((error_count / span_count) * 100, 2) if span_count > 0 else 0.0,
                "duration_p50": p50,
                "duration_p95": p95,
                "duration_p99": p99,
            }
            result.append(service_info)

        await self._cache_set_json_safe(snapshot_key, result, SERVICE_SNAPSHOT_TTL_SECONDS)
        await self._cache_set_json_safe(cache_key, result, SERVICE_VIEW_CACHE_TTL)
        return result

    async def _get_service_red_metrics(self, service_name: str) -> Dict[str, Any]:
        red = {
            "rate": None,
            "error_rate": None,
            "duration_p50": None,
            "duration_p95": None,
            "duration_p99": None,
        }

        try:
            all_metrics = await self.get_metric_names()
            duration_metric = "traces.span.metrics.duration"
            calls_metric = "traces.span.metrics.calls"

            if duration_metric not in all_metrics:
                return red

            resource_filter = {"service.name": service_name}
            end_time = time.time()
            start_time = end_time - 300

            duration_series = await self.get_metric_series(
                duration_metric,
                resource_filter=resource_filter,
                start_time=start_time,
                end_time=end_time,
            )

            calls_series = []
            if calls_metric in all_metrics:
                calls_series = await self.get_metric_series(
                    calls_metric,
                    resource_filter=resource_filter,
                    start_time=start_time,
                    end_time=end_time,
                )

            if not duration_series:
                return red

            bucket_size = 15
            grouped_by_time: Dict[int, Dict[str, Any]] = {}

            for series in duration_series:
                for point in series["datapoints"]:
                    ts = point["timestamp"]
                    bucket_ts = int(ts / bucket_size) * bucket_size
                    if bucket_ts not in grouped_by_time:
                        grouped_by_time[bucket_ts] = {"count": 0, "buckets": []}

                    hist = point.get("histogram", {})
                    if hist:
                        grouped_by_time[bucket_ts]["count"] += hist.get("count", 0)
                        grouped_by_time[bucket_ts]["buckets"].append(
                            {
                                "counts": hist.get("bucketCounts", []),
                                "bounds": hist.get("explicitBounds", []),
                            }
                        )

            if len(grouped_by_time) >= 1:
                sorted_times = sorted(grouped_by_time.keys())
                latest_ts = sorted_times[-1]
                latest = grouped_by_time[latest_ts]

                if len(grouped_by_time) >= 2:
                    previous_ts = sorted_times[-2]
                    previous = grouped_by_time[previous_ts]
                    count_latest = latest["count"]
                    count_prev = previous["count"]
                    time_diff = latest_ts - previous_ts
                    if time_diff > 0 and count_latest > count_prev:
                        import math

                        red["rate"] = math.ceil((count_latest - count_prev) / time_diff)
                else:
                    import math

                    red["rate"] = math.ceil(latest["count"] / bucket_size)

                if calls_series:
                    total_calls = 0
                    error_calls = 0
                    for series in calls_series:
                        attrs = series.get("attributes", {})
                        status_code = attrs.get("status.code") or attrs.get("http.response.status_code")
                        for point in series["datapoints"]:
                            value = point.get("value", 0)
                            total_calls += value
                            if status_code == "STATUS_CODE_ERROR" or status_code == "ERROR" or (
                                isinstance(status_code, int) and status_code >= 400
                            ):
                                error_calls += value

                    if total_calls > 0:
                        red["error_rate"] = round((error_calls / total_calls) * 100, 2)

                latest_buckets_list = latest["buckets"]
                if latest_buckets_list:
                    bounds = latest_buckets_list[0]["bounds"]
                    if bounds:
                        num_buckets = len(bounds) + 1
                        aggregated_counts = [0] * num_buckets
                        total_count = 0

                        for entry in latest_buckets_list:
                            counts = entry["counts"]
                            if len(counts) == num_buckets:
                                for i in range(num_buckets):
                                    aggregated_counts[i] += counts[i]
                                    total_count += counts[i]

                        if total_count > 0:
                            cumulative = 0
                            prev_bound = 0
                            for i, count in enumerate(aggregated_counts):
                                cumulative += count
                                percentile = (cumulative / total_count) * 100
                                bound_ms = bounds[i] if i < len(bounds) else None
                                if bound_ms is None:
                                    continue

                                if red["duration_p50"] is None and percentile >= 50:
                                    red["duration_p50"] = round((prev_bound + bound_ms) / 2, 2)
                                if red["duration_p95"] is None and percentile >= 95:
                                    red["duration_p95"] = round((prev_bound + bound_ms) / 2, 2)
                                if red["duration_p99"] is None and percentile >= 99:
                                    red["duration_p99"] = round((prev_bound + bound_ms) / 2, 2)

                                prev_bound = bound_ms
        except Exception as e:
            logger.error(f"Error fetching RED metrics for {service_name}: {e}", exc_info=True)

        return red

    async def get_stats(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            cardinality = await self.get_cardinality_stats()

            async with conn.execute("SELECT COUNT(*) FROM trace_index WHERE expires_at > ?", (now,)) as cur:
                trace_count = int((await cur.fetchone())[0])
            async with conn.execute("SELECT COUNT(*) FROM span_index WHERE expires_at > ?", (now,)) as cur:
                span_count = int((await cur.fetchone())[0])
            async with conn.execute("SELECT COUNT(*) FROM logs WHERE expires_at > ?", (now,)) as cur:
                log_count = int((await cur.fetchone())[0])

            return {
                "traces": trace_count,
                "spans": span_count,
                "logs": log_count,
                "metrics": cardinality["current"],
                "metrics_max": cardinality["max"],
                "metrics_dropped": cardinality["dropped_count"],
            }
        finally:
            await conn.close()

    async def get_admin_stats(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            cardinality = await self.get_cardinality_stats()

            async with conn.execute("SELECT COUNT(*) FROM trace_index WHERE expires_at > ?", (now,)) as cur:
                trace_count = int((await cur.fetchone())[0])
            async with conn.execute("SELECT COUNT(*) FROM span_index WHERE expires_at > ?", (now,)) as cur:
                span_count = int((await cur.fetchone())[0])
            async with conn.execute("SELECT COUNT(*) FROM logs WHERE expires_at > ?", (now,)) as cur:
                log_count = int((await cur.fetchone())[0])

            async with conn.execute("PRAGMA page_count") as cur:
                page_count = int((await cur.fetchone())[0])
            async with conn.execute("PRAGMA page_size") as cur:
                page_size = int((await cur.fetchone())[0])

            size_bytes = page_count * page_size
            db_stats = {
                "path": self.db_path,
                "size_bytes": size_bytes,
                "size_human": f"{round(size_bytes / (1024 * 1024), 2)}MB",
                "page_count": page_count,
                "page_size": page_size,
                "max_size_bytes": self.max_db_size_bytes,
            }

            cardinality_info = {
                "current": cardinality["current"],
                "max": cardinality["max"],
                "dropped": cardinality["dropped_count"],
                "percent_used": round((cardinality["current"] / cardinality["max"]) * 100, 2)
                if cardinality["max"] > 0
                else 0,
            }

            return {
                "telemetry": {
                    "traces": trace_count,
                    "spans": span_count,
                    "logs": log_count,
                    "metrics": cardinality["current"],
                },
                "db": db_stats,
                "cardinality": cardinality_info,
            }
        finally:
            await conn.close()
