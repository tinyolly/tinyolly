"""Log parsing, storage and queries."""


import time
import uuid
from typing import Any, Dict, List, Optional

from .otlp_utils import (
    extract_resource_attributes,
    normalize_id,
    parse_attributes,
)
from .storage_common import logger


class LogsMixin:
    """Log parsing, storage and queries."""

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

                    trace_id = normalize_id(log_record.get("traceId"), 16)
                    span_id = normalize_id(log_record.get("spanId"), 8)

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
        await self._retry_locked(lambda: self._store_logs_once(logs))

    async def _store_logs_once(self, logs: List[Dict[str, Any]]) -> None:
        if not logs:
            return

        await self._ensure_initialized()
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN IMMEDIATE")
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
