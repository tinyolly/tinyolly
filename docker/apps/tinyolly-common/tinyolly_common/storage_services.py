"""Response cache helpers, service graph, service catalog and stats."""


import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import orjson

from .mesh_adapters import (
    annotate_clusters,
    graph_node_list,
    merge_graph,
    metric_edges,
    metric_namespaces,
    metric_only_edge,
    posture,
    trace_edge,
)
from .otlp_utils import (
    get_attr_value,
    is_error_status,
)
from .storage_common import SERVICE_RESET_TTL_SECONDS, SERVICE_SNAPSHOT_TTL_SECONDS, SERVICE_VIEW_CACHE_TTL, logger


class ServicesMixin:
    """Response cache helpers, service graph, service catalog and stats."""

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

    async def get_service_graph(self, limit: int = 500, merge: bool = True) -> Dict[str, Any]:
        cache_key = f"service_graph_cache_v4:{limit}:merge={merge}"
        snapshot_key = self._service_snapshot_key("map")
        reset_at = await self._get_service_reset_ts("map")
        trace_ids = await self.get_recent_traces(limit, since_ts=reset_at)

        # Mesh metrics (z-tunnel / sidecar) describe service-to-service traffic even when no traces
        # are stored, so fetch them up front and merge them into the graph below.
        metric_edges_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        try:
            tcp_series = await self.get_metric_series("istio_tcp_connections_opened_total")
            req_series = await self.get_metric_series("istio_requests_total")
            failed_series = await self.get_metric_series("istio_tcp_connections_failed_total")  # DENY flag = refused by policy
            all_series = tcp_series + req_series + failed_series
            for edge in metric_edges(all_series):
                metric_edges_map[(edge["source"], edge["target"])] = edge
            namespaces = metric_namespaces(all_series)
        except Exception as e:
            logger.warning(f"Service graph: metric edges unavailable: {e}")
            namespaces = set()

        if not trace_ids:
            if not metric_edges_map:
                snapshot = await self._cache_get_json(snapshot_key)
                return snapshot or {"nodes": [], "edges": []}
            nodes = {}
            for (source, target) in metric_edges_map:
                for name in (source, target):
                    if name not in nodes:
                        nodes[name] = {"type": "service", "metrics": {}}
            graph_nodes = graph_node_list(nodes)
            graph_edges = [metric_only_edge(source, target, edge) for (source, target), edge in metric_edges_map.items()]
            result = annotate_clusters(merge_graph({"nodes": graph_nodes, "edges": graph_edges}, namespaces if merge else set()))
            await self._cache_set_json_safe(snapshot_key, result, SERVICE_SNAPSHOT_TTL_SECONDS)
            await self._cache_set_json_safe(cache_key, result, SERVICE_VIEW_CACHE_TTL)
            return result

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

                is_error = is_error_status(span.get("status", {}) or {})

                if target_node:
                    if target_node not in nodes:
                        nodes[target_node] = {"type": node_type, "metrics": {}}
                    key = (service, target_node)
                    if key not in edges:
                        edges[key] = {"count": 0, "durations": [], "spans": []}
                    edges[key]["count"] += 1
                    edges[key]["durations"].append(duration_ms)
                    edges[key]["spans"].append((start, end, is_error))

                parent_id = span.get("parentSpanId", span.get("parent_span_id"))
                if parent_id and parent_id in span_map:
                    parent = span_map[parent_id]
                    parent_service = parent.get("serviceName", "unknown")
                    if parent_service != service and parent_service != "unknown" and service != "unknown":
                        key = (parent_service, service)
                        if key not in edges:
                            edges[key] = {"count": 0, "durations": [], "spans": []}
                        edges[key]["count"] += 1
                        edges[key]["durations"].append(duration_ms)
                        edges[key]["spans"].append((start, end, is_error))

        graph_edges = [trace_edge(source, target, data, metric_edges_map.get((source, target)))
                       for (source, target), data in edges.items()]

        # Metric-only edges (no trace for the pair): add them, and any endpoint nodes they need.
        for (source, target), edge in metric_edges_map.items():
            if (source, target) in edges:
                continue
            for name in (source, target):
                if name not in nodes:
                    nodes[name] = {"type": "service", "metrics": {}}
            graph_edges.append(metric_only_edge(source, target, edge))

        graph_nodes = graph_node_list(nodes)

        result = annotate_clusters(merge_graph({"nodes": graph_nodes, "edges": graph_edges}, namespaces if merge else set()))
        await self._cache_set_json_safe(snapshot_key, result, SERVICE_SNAPSHOT_TTL_SECONDS)
        await self._cache_set_json_safe(cache_key, result, SERVICE_VIEW_CACHE_TTL)
        return result

    async def get_mesh_posture(self) -> Dict[str, Any]:
        """Mesh posture summary (mTLS coverage, plaintext edges, denied edges) from the merged service graph."""
        return posture(await self.get_service_graph())

    async def get_service_catalog(self) -> List[Dict[str, Any]]:
        cache_key = self._service_cache_key("catalog")
        snapshot_key = self._service_snapshot_key("catalog")
        reset_at = await self._get_service_reset_ts("catalog")

        # Check the short-lived cache BEFORE decoding up to 10,000 span blobs.
        cached_catalog = await self._cache_get_json(cache_key)
        if cached_catalog:
            return cached_catalog

        spans = await self._get_recent_spans_data(10000, since_ts=reset_at)
        if not spans:
            snapshot = await self._cache_get_json(snapshot_key)
            return snapshot or []

        services: Dict[str, Dict[str, Any]] = {}

        for span in spans:
            service_name = span.get("serviceName") or span.get("service_name") or "unknown"
            trace_id = span.get("traceId") or span.get("trace_id")
            start_time = int(span.get("startTimeUnixNano", span.get("start_time", 0)) or 0)
            end_time = int(span.get("endTimeUnixNano", span.get("end_time", 0)) or 0)
            duration_ms = (end_time - start_time) / 1_000_000 if end_time > start_time else 0.0
            kind = span.get("kind", 0)
            is_error = is_error_status(span.get("status", {}) or {})

            if service_name not in services:
                services[service_name] = {
                    "name": service_name,
                    "trace_ids": set(),
                    "first_seen": start_time,
                    "last_seen": start_time,
                    "spans": [],
                }

            services[service_name]["trace_ids"].add(trace_id)
            services[service_name]["first_seen"] = min(services[service_name]["first_seen"], start_time)
            services[service_name]["last_seen"] = max(services[service_name]["last_seen"], start_time)
            services[service_name]["spans"].append((kind, start_time, end_time, duration_ms, is_error))

        counted_kinds = (2, 5, "SPAN_KIND_SERVER", "SPAN_KIND_CONSUMER")
        result = []
        for data in services.values():
            all_spans = data["spans"]
            counted = [s for s in all_spans if s[0] in counted_kinds]
            if not counted:
                counted = all_spans

            span_count = len(all_spans)
            counted_count = len(counted)
            error_count = sum(1 for s in counted if s[4])

            durations = sorted(s[3] for s in counted)
            p50 = None
            p95 = None
            p99 = None
            if durations:
                p50 = round(durations[int((len(durations) - 1) * 0.50)], 2)
                p95 = round(durations[int((len(durations) - 1) * 0.95)], 2)
                p99 = round(durations[int((len(durations) - 1) * 0.99)], 2)

            if counted_count > 0:
                min_start = min(s[1] for s in counted)
                max_end = max(s[2] for s in counted)
                window = max((max_end - min_start) / 1_000_000_000, 1.0)
                rate = round(counted_count / window, 2)
            else:
                rate = 0

            error_rate = round((error_count / counted_count) * 100, 2) if counted_count > 0 else 0.0

            service_info = {
                "name": data["name"],
                "span_count": span_count,
                "trace_count": len(data["trace_ids"]),
                "first_seen": data["first_seen"],
                "last_seen": data["last_seen"],
                "rate": rate,
                "error_rate": error_rate,
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
