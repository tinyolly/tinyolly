"""Trace and span parsing, storage and queries."""


import time
from typing import Any, Dict, List, Optional

from .otlp_utils import (
    extract_resource_attributes,
    get_attr_value,
    is_error_status,
    normalize_id,
)
from .storage_common import logger


class SpansMixin:
    """Trace and span parsing, storage and queries."""

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
                    trace_id = normalize_id(span_data.get("traceId"), 16)
                    span_id = normalize_id(span_data.get("spanId"), 8)
                    parent_span_id = normalize_id(span_data.get("parentSpanId"), 8)

                    # A span without valid ids cannot be stored or linked; skip it, not the whole batch.
                    if not trace_id or not span_id:
                        continue

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
        await self._retry_locked(lambda: self._store_spans_once(spans))

    async def _store_spans_once(self, spans: List[Dict[str, Any]]) -> None:
        if not spans:
            return

        await self._ensure_initialized()
        now = time.time()
        expires_at = now + self.ttl

        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN IMMEDIATE")
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
                    # (the legacy `traces` table duplicated every span blob and was never read; no longer written)

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

            return self._span_to_details(span_id, self._decompress_if_needed(row[0]))
        except Exception as e:
            logger.error(f"Error getting span details: {e}", exc_info=True)
            return None
        finally:
            await conn.close()

    def _span_to_details(self, span_id: str, span: Dict[str, Any]) -> Dict[str, Any]:
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

    async def get_spans_details_batch(self, span_ids: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not span_ids:
            return results

        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()          # one connection for the whole batch (was one per span id)
        try:
            by_id: Dict[str, Dict[str, Any]] = {}
            for i in range(0, len(span_ids), 500):
                chunk = span_ids[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                async with conn.execute(
                    f"SELECT span_id, data FROM spans WHERE expires_at > ? AND span_id IN ({placeholders})",
                    [now, *chunk],
                ) as cur:
                    for row in await cur.fetchall():
                        try:
                            by_id[row[0]] = self._span_to_details(row[0], self._decompress_if_needed(row[1]))
                        except Exception as e:
                            logger.error(f"Error building span details for {row[0]}: {e}")
            return [by_id[sid] for sid in span_ids if sid in by_id]     # keep the requested order
        finally:
            await conn.close()

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
        return self._summarize_spans(trace_id, await self.get_trace_spans(trace_id))

    async def get_trace_summaries(self, trace_ids: List[str]) -> List[Dict[str, Any]]:
        """Summaries for many traces with a few batched queries (get_trace_summary per id opened one connection each)."""
        spans_by_trace = await self._get_trace_spans_batch(trace_ids)
        out = []
        for tid in trace_ids:
            summary = self._summarize_spans(tid, spans_by_trace.get(tid, []))
            if summary:
                out.append(summary)
        return out

    def _summarize_spans(self, trace_id: str, spans: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not spans:
            return None

        start_times = [int(s.get("startTimeUnixNano", s.get("start_time", 0))) for s in spans]
        end_times = [int(s.get("endTimeUnixNano", s.get("end_time", 0))) for s in spans]
        min_start = min(start_times) if start_times else 0
        max_end = max(end_times) if end_times else 0
        duration_ns = max_end - min_start

        root_span = next((s for s in spans if not s.get("parentSpanId") and not s.get("parent_span_id")), spans[0])

        error_count = sum(1 for s in spans if is_error_status(s.get("status", {}) or {}))

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
            "error_count": error_count,
            "has_error": error_count > 0,
            "root_span_server_name": root_span_server_name,
            "root_span_scheme": root_span_scheme,
            "root_span_host": root_span_host,
            "root_span_target": root_span_target,
            "root_span_url": root_span_url,
            "service_name": root_span_service_name,
        }
