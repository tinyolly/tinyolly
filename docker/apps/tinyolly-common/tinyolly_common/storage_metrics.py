"""Metric parsing, storage and queries."""


import json
import time
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import orjson
from async_lru import alru_cache

from .otlp_utils import (
    exponential_to_explicit,
    extract_resource_attributes,
    normalize_id,
    parse_attributes,
)
from .storage_common import logger


class MetricsMixin:
    """Metric parsing, storage and queries."""

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
                    elif "exponentialHistogram" in metric:
                        # Stored as an explicit-bucket histogram (see exponential_to_explicit) so every existing
                        # reader/chart works; these used to be silently dropped (nothing stored, nothing shown).
                        metric_type = "histogram"
                        exp = metric["exponentialHistogram"]
                        metric_datapoints = exp.get("dataPoints", [])
                        temporality = exp.get("aggregationTemporality", "CUMULATIVE")

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
                        elif metric_type == "histogram" and ("scale" in dp or "positive" in dp or "zeroCount" in dp) and "explicitBounds" not in dp:
                            value = dp.get("sum", 0)
                            histogram_data = exponential_to_explicit(dp)
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

                            # same hex form as spans so exemplar -> trace links resolve
                            trace_id = normalize_id(ex.get("traceId"), 16)
                            span_id = normalize_id(ex.get("spanId"), 8)

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
        await self._write_datapoints([{
            "name": name, "type": metric_type, "unit": unit, "description": description,
            "temporality": temporality, "resource": resource, "attributes": attributes, "value": value,
            "timestamp": timestamp, "histogram": histogram, "summary": summary, "exemplars": exemplars,
        }])

    async def _write_datapoints(self, datapoints: List[Dict[str, Any]]) -> None:
        await self._retry_locked(lambda: self._write_datapoints_once(datapoints))

    async def _write_datapoints_once(self, datapoints: List[Dict[str, Any]]) -> None:
        """Write many datapoints on ONE connection in ONE transaction (was a connection + transaction per point).

        Cardinality protection: a metric name that is not yet stored is dropped once `max_cardinality`
        distinct live names exist; drops are counted in cardinality_meta (shown as metrics_dropped).
        """
        if not datapoints:
            return
        await self._ensure_initialized()
        now = time.time()
        expires_at = now + self.ttl

        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN IMMEDIATE")
                async with conn.execute("SELECT name FROM metrics_names WHERE expires_at > ?", (now,)) as cur:
                    known = {row[0] for row in await cur.fetchall()}
                dropped = 0
                dropped_names: List[str] = []

                for dp in datapoints:
                    name = dp["name"]
                    if name not in known:
                        if len(known) >= self.max_cardinality:
                            dropped += 1
                            if name not in dropped_names:
                                dropped_names.append(name)
                            continue
                        known.add(name)
                    await self._write_one_datapoint(conn, dp, expires_at)

                if dropped:
                    await self._record_dropped(conn, dropped, dropped_names)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()

    async def _record_dropped(self, conn: aiosqlite.Connection, count: int, names: List[str]) -> None:
        async with conn.execute("SELECT value FROM cardinality_meta WHERE key='metric_dropped_count'") as cur:
            row = await cur.fetchone()
        total = (int(row[0]) if row and row[0] else 0) + count
        async with conn.execute("SELECT value FROM cardinality_meta WHERE key='metric_dropped_names'") as cur:
            row = await cur.fetchone()
        try:
            existing = json.loads(row[0]) if row and row[0] else []
        except Exception:
            existing = []
        merged = (existing + [n for n in names if n not in existing])[-50:]
        await conn.execute("INSERT OR REPLACE INTO cardinality_meta(key, value) VALUES ('metric_dropped_count', ?)", (str(total),))
        await conn.execute("INSERT OR REPLACE INTO cardinality_meta(key, value) VALUES ('metric_dropped_names', ?)", (json.dumps(merged),))
        logger.warning(f"Metric cardinality limit ({self.max_cardinality}) reached: dropped {count} datapoint(s) for new names {names[:5]}")

    async def _write_one_datapoint(self, conn: aiosqlite.Connection, dp: Dict[str, Any], expires_at: float) -> None:
        name = dp["name"]
        resource = dp.get("resource") or {}
        attributes = dp.get("attributes") or {}
        timestamp = dp["timestamp"]
        exemplars = dp.get("exemplars")
        resource_hash = self._hash_dict(resource)
        attr_hash = self._hash_dict(attributes)

        await conn.execute("INSERT OR REPLACE INTO metrics_names(name, expires_at) VALUES (?, ?)", (name, expires_at))
        meta_data = {
            "type": dp.get("type", "unknown"),
            "unit": dp.get("unit", ""),
            "description": dp.get("description", ""),
            "temporality": dp.get("temporality") or "N/A",
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
            "value": dp.get("value"),
            "timestamp": timestamp,
            "histogram": dp.get("histogram"),
            "summary": dp.get("summary"),
        }
        await conn.execute(
            """
            INSERT INTO metrics_series(name, resource_hash, attr_hash, ts, expires_at, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, resource_hash, attr_hash, timestamp, expires_at, self._compress_for_storage(datapoint_data)),
        )
        for ex in exemplars or []:
            await conn.execute(
                """
                INSERT INTO metrics_exemplars(name, resource_hash, attr_hash, ts, expires_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, resource_hash, attr_hash, float(ex.get("timestamp", timestamp)), expires_at, self._compress_for_storage(ex)),
            )

    async def store_metric(self, metric: Dict[str, Any]) -> None:
        await self.store_metrics([metric])

    async def store_metrics(self, metrics: Any) -> None:
        if not metrics:
            return

        if isinstance(metrics, dict) and ("resourceMetrics" in metrics or "resource_metrics" in metrics):
            await self._write_datapoints(self.parse_otlp_metrics(metrics))
            return

        legacy_metrics = metrics if isinstance(metrics, list) else [metrics]
        batch = []
        for metric in legacy_metrics:
            name = metric.get("name")
            if not name:
                continue
            batch.append({
                "name": name,
                "type": metric.get("type", "unknown"),
                "unit": metric.get("unit", ""),
                "description": metric.get("description", ""),
                "temporality": metric.get("temporality", "N/A"),
                "resource": metric.get("resource", {}),
                "attributes": metric.get("attributes", {}),
                "value": metric.get("value"),
                "timestamp": float(metric.get("timestamp", time.time())),
                "histogram": metric.get("histogram"),
                "summary": metric.get("summary"),
                "exemplars": metric.get("exemplars", []),
            })
        await self._write_datapoints(batch)

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
