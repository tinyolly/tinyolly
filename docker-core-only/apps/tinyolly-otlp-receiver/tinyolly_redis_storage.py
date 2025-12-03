"""
TinyOlly Storage Module (Async)
Handles all Redis interactions for traces, logs, and metrics using async operations.
Optimized with MessagePack, ZSTD, and Batch Operations.
"""
import zstandard as zstd
import base64
import json
import time
import uuid
import os
import msgpack
import orjson
from redis import asyncio as aioredis
from async_lru import alru_cache

# Default configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT_NUMBER', os.getenv('REDIS_PORT_OVERRIDE', '6579')))
TTL_SECONDS = int(os.getenv('REDIS_TTL', 1800))  # 30 minutes default
MAX_METRIC_CARDINALITY = int(os.getenv('MAX_METRIC_CARDINALITY', 1000))

# ZSTD Contexts (reusing context is faster)
zstd_compressor = zstd.ZstdCompressor(level=3)
zstd_decompressor = zstd.ZstdDecompressor()

class Storage:
    def __init__(self, host=REDIS_HOST, port=REDIS_PORT, ttl=TTL_SECONDS, max_cardinality=MAX_METRIC_CARDINALITY):
        self.host = host
        self.port = port
        self.ttl = ttl
        self.max_cardinality = max_cardinality
        self._client = None
    
    async def get_client(self):
        """Get or create async Redis client"""
        if self._client is None:
            self._client = await aioredis.from_url(
                f"redis://{self.host}:{self.port}",
                encoding="utf-8",
                decode_responses=False,  # Changed to False for binary data (msgpack/zstd)
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
        return self._client

    async def is_connected(self):
        try:
            client = await self.get_client()
            await client.ping()
            return True
        except:
            return False

    def _compress_for_storage(self, data):
        """Serialize with msgpack and compress with ZSTD if needed"""
        # Serialize
        packed = msgpack.packb(data)
        
        # Compress if larger than 512 bytes
        if len(packed) > 512:
            compressed = zstd_compressor.compress(packed)
            return b'ZSTD:' + compressed
        return packed

    def _decompress_if_needed(self, data):
        """Decompress ZSTD data and unpack msgpack"""
        if not data:
            return {}
            
        try:
            # Handle legacy ZLIB data (backward compatibility attempt, though flush recommended)
            if isinstance(data, str) and data.startswith('ZLIB_B64:'):
                import zlib
                compressed = base64.b64decode(data[9:])
                decompressed = zlib.decompress(compressed)
                return json.loads(decompressed)
            
            # Handle ZSTD compressed data
            if data.startswith(b'ZSTD:'):
                decompressed = zstd_decompressor.decompress(data[5:])
                return msgpack.unpackb(decompressed)
            
            # Handle uncompressed msgpack
            return msgpack.unpackb(data)
        except Exception as e:
            print(f"Deserialization error: {e}")
            return {}
    
    def _normalize_datapoint(self, dp):
        """Normalize datapoint to ensure all numeric values are proper types"""
        normalized = {
            'timestamp': dp['timestamp'],
            'value': float(dp['value']) if dp['value'] is not None else None,
            'histogram': None,
            'summary': None
        }
        
        # Normalize histogram data
        if dp.get('histogram'):
            hist = dp['histogram']
            normalized['histogram'] = {
                'count': int(hist['count']) if isinstance(hist['count'], str) else hist['count'],
                'sum': float(hist['sum']) if hist['sum'] is not None else 0,
                'bucketCounts': [int(c) if isinstance(c, str) else c for c in hist.get('bucketCounts', [])],
                'explicitBounds': [float(b) if b is not None else 0 for b in hist.get('explicitBounds', [])]
            }
        
        # Normalize summary data
        if dp.get('summary'):
            summ = dp['summary']
            normalized['summary'] = {
                'count': int(summ['count']) if isinstance(summ['count'], str) else summ['count'],
                'sum': float(summ['sum']) if summ['sum'] is not None else 0,
                'quantileValues': [
                    {
                        'quantile': float(qv['quantile']) if qv.get('quantile') is not None else 0,
                        'value': float(qv['value']) if qv.get('value') is not None else 0
                    }
                    for qv in summ.get('quantileValues', [])
                ]
            }
        
        return normalized

    def parse_otlp_traces(self, otlp_data):
        """Parse OTLP trace format and extract spans with full context"""
        spans = []
        
        resource_spans_list = otlp_data.get('resourceSpans', [])
        
        for resource_spans in resource_spans_list:
            # Extract resource attributes
            resource = resource_spans.get('resource', {})
            resource_attrs = self.extract_resource_attributes(resource)
            service_name = resource_attrs.get('service.name', 'unknown')
            
            # Process scope spans
            for scope_spans in resource_spans.get('scopeSpans', []):
                scope = scope_spans.get('scope', {})
                
                # Process each span
                for span_data in scope_spans.get('spans', []):
                    # Extract IDs - convert from base64 to hex
                    trace_id_b64 = span_data.get('traceId', '')
                    span_id_b64 = span_data.get('spanId', '')
                    parent_span_id_b64 = span_data.get('parentSpanId', '')
                    
                    if not trace_id_b64 or not span_id_b64:
                        continue
                    
                    # Convert base64 to hex
                    trace_id = base64.b64decode(trace_id_b64).hex() if trace_id_b64 else ''
                    span_id = base64.b64decode(span_id_b64).hex() if span_id_b64 else ''
                    parent_span_id = base64.b64decode(parent_span_id_b64).hex() if parent_span_id_b64 else ''
                    
                    # Build span record
                    span_record = {
                        'traceId': trace_id,
                        'spanId': span_id,
                        'name': span_data.get('name', ''),
                        'kind': span_data.get('kind', 0),
                        'startTimeUnixNano': span_data.get('startTimeUnixNano', '0'),
                        'endTimeUnixNano': span_data.get('endTimeUnixNano', '0'),
                        'parentSpanId': parent_span_id,
                        'attributes': span_data.get('attributes', []),
                        'status': span_data.get('status', {}),
                        'serviceName': service_name,
                        'resource': resource_attrs,  # Store full resource context
                        'scope': {
                            'name': scope.get('name', ''),
                            'version': scope.get('version', '')
                        }
                    }
                    
                    spans.append(span_record)
        
        return spans
    
    async def store_traces(self, otlp_data):
        """Store traces in OTLP format by parsing and delegating to store_spans"""
        spans = self.parse_otlp_traces(otlp_data)
        if spans:
            await self.store_spans(spans)
    
    async def store_span(self, span):
        """Store a single span (legacy wrapper around batch)"""
        await self.store_spans([span])

    async def store_spans(self, spans):
        """Store multiple spans efficiently"""
        if not spans:
            return

        try:
            client = await self.get_client()
            pipe = client.pipeline()
            
            for span in spans:
                trace_id = span.get('traceId') or span.get('trace_id')
                span_id = span.get('spanId') or span.get('span_id')
                
                if not trace_id or not span_id:
                    continue
                
                # Check if trace exists (optimization: skip if we know we just added it in this batch? 
                # For simplicity, we'll just do the operations, Redis handles sets efficiently)
                
                trace_key = f"trace:{trace_id}"
                span_key = f"span:{span_id}"
                
                # Prepare data
                packed_data = self._compress_for_storage(span)
                
                # Add commands to pipeline
                pipe.setex(span_key, self.ttl, packed_data)
                pipe.sadd(trace_key, span_id)
                pipe.expire(trace_key, self.ttl)
                
                # Update indices
                pipe.zadd('trace_index', {trace_id: time.time()})
                pipe.expire('trace_index', self.ttl)
                
                trace_span_key = f"trace:{trace_id}:spans"
                pipe.rpush(trace_span_key, packed_data)
                pipe.expire(trace_span_key, self.ttl)
                
                pipe.zadd('span_index', {span_id: time.time()})
                pipe.expire('span_index', self.ttl)
            
            await pipe.execute()
        except Exception as e:
            print(f"Redis error in store_spans: {e}")

    async def get_recent_traces(self, limit=100):
        """Get recent trace IDs"""
        client = await self.get_client()
        # ZREVRANGE returns bytes when decode_responses=False, need to decode IDs
        ids = await client.zrevrange('trace_index', 0, limit - 1)
        return [id.decode('utf-8') for id in ids]

    async def get_recent_spans(self, limit=100):
        """Get recent span IDs"""
        client = await self.get_client()
        ids = await client.zrevrange('span_index', 0, limit - 1)
        return [id.decode('utf-8') for id in ids]

    async def get_span_details(self, span_id):
        """Get details for a specific span"""
        span_key = f"span:{span_id}"
        try:
            client = await self.get_client()
            span_data = await client.get(span_key)
            
            if not span_data:
                return None
                
            span = self._decompress_if_needed(span_data)
            
            # Extract attributes for display
            def get_attr(obj, keys):
                # Handle OTLP list of dicts format
                attributes = obj.get('attributes')
                if isinstance(attributes, list):
                    for attr in attributes:
                        if attr['key'] in keys:
                            val = attr['value']
                            # Return the first non-null value found
                            for k in ['stringValue', 'intValue', 'boolValue', 'doubleValue']:
                                if k in val:
                                    return val[k]
                # Handle dict format (if normalized)
                elif isinstance(attributes, dict):
                    for k in keys:
                        if k in attributes:
                            return attributes[k]
                return None

            method = get_attr(span, ['http.method', 'http.request.method'])
            route = get_attr(span, ['http.route', 'http.target', 'url.path'])
            status_code = get_attr(span, ['http.status_code', 'http.response.status_code'])
            server_name = get_attr(span, ['http.server_name', 'net.host.name'])
            scheme = get_attr(span, ['http.scheme', 'url.scheme'])
            host = get_attr(span, ['http.host', 'net.host.name'])
            target = get_attr(span, ['http.target', 'url.path'])
            url = get_attr(span, ['http.url', 'url.full'])
            
            start_time = int(span.get('startTimeUnixNano', span.get('start_time', 0)))
            end_time = int(span.get('endTimeUnixNano', span.get('end_time', 0)))
            duration_ns = end_time - start_time if end_time > start_time else 0

            return {
                'span_id': span_id,
                'trace_id': span.get('traceId') or span.get('trace_id'),
                'name': span.get('name', 'unknown'),
                'start_time': start_time,
                'duration_ms': duration_ns / 1_000_000,
                'method': method,
                'route': route,
                'status_code': status_code,
                'status': span.get('status', {}),
                'server_name': server_name,
                'scheme': scheme,
                'host': host,
                'target': target,
                'url': url,
                'service_name': span.get('serviceName', 'unknown')
            }
        except Exception as e:
            print(f"Error getting span details: {e}")
            return None

    async def get_trace_spans(self, trace_id):
        """Get all spans for a trace"""
        trace_key = f"trace:{trace_id}:spans"
        try:
            client = await self.get_client()
            span_data_list = await client.lrange(trace_key, 0, -1)
            
            if not span_data_list:
                return []
                
            return [self._decompress_if_needed(s) for s in span_data_list]
        except Exception as e:
            print(f"Error getting trace spans: {e}")
            return []

    async def get_trace_summary(self, trace_id):
        """Get summary of a trace"""
        spans = await self.get_trace_spans(trace_id)
        if not spans:
            return None
            
        # Calculate trace duration
        start_times = [int(s.get('startTimeUnixNano', s.get('start_time', 0))) for s in spans]
        end_times = [int(s.get('endTimeUnixNano', s.get('end_time', 0))) for s in spans]
        
        min_start = min(start_times) if start_times else 0
        max_end = max(end_times) if end_times else 0
        duration_ns = max_end - min_start
        
        # Find root span (no parent)
        root_span = next((s for s in spans if not s.get('parentSpanId') and not s.get('parent_span_id')), spans[0] if spans else None)
        
        # Extract root span details
        root_span_method = None
        root_span_route = None
        root_span_status_code = None
        root_span_server_name = None
        root_span_scheme = None
        root_span_host = None
        root_span_target = None
        root_span_url = None
        root_span_service_name = None
        
        if root_span:
            # Helper to get attribute value
            def get_attr(span, keys):
                attributes = span.get('attributes', [])
                if isinstance(attributes, list):
                    for attr in attributes:
                        if attr.get('key') in keys:
                            val = attr.get('value', {})
                            if 'stringValue' in val: return val['stringValue']
                            if 'intValue' in val: return val['intValue']
                            if 'boolValue' in val: return val['boolValue']
                            return str(val)
                elif isinstance(attributes, dict):
                    for key in keys:
                        if key in attributes:
                            return attributes[key]
                return None

            root_span_method = get_attr(root_span, ['http.method', 'http.request.method'])
            root_span_route = get_attr(root_span, ['http.route', 'http.target', 'url.path'])
            root_span_status_code = get_attr(root_span, ['http.status_code', 'http.response.status_code'])
            root_span_server_name = get_attr(root_span, ['http.server_name', 'net.host.name'])
            root_span_scheme = get_attr(root_span, ['http.scheme', 'url.scheme'])
            root_span_host = get_attr(root_span, ['http.host', 'net.host.name'])
            root_span_target = get_attr(root_span, ['http.target', 'url.path'])
            root_span_url = get_attr(root_span, ['http.url', 'url.full'])
            root_span_service_name = root_span.get('serviceName', 'unknown')
            
        return {
            'trace_id': trace_id,
            'span_count': len(spans),
            'duration_ms': duration_ns / 1_000_000 if duration_ns else 0,
            'start_time': min_start,
            'root_span_name': root_span.get('name', 'unknown') if root_span else 'unknown',
            'root_span_method': root_span_method,
            'root_span_route': root_span_route,
            'root_span_status_code': root_span_status_code,
            'root_span_status': root_span.get('status', {}) if root_span else {},
            'root_span_server_name': root_span_server_name,
            'root_span_scheme': root_span_scheme,
            'root_span_host': root_span_host,
            'root_span_target': root_span_target,
            'root_span_url': root_span_url,
            'service_name': root_span_service_name
        }

    def parse_otlp_logs(self, otlp_data):
        """Parse OTLP log format and extract log records with full context"""
        logs = []
        
        resource_logs_list = otlp_data.get('resourceLogs', [])
        
        for resource_logs in resource_logs_list:
            # Extract resource attributes
            resource = resource_logs.get('resource', {})
            resource_attrs = self.extract_resource_attributes(resource)
            service_name = resource_attrs.get('service.name', 'unknown')
            
            # Process scope logs
            for scope_logs in resource_logs.get('scopeLogs', []):
                scope = scope_logs.get('scope', {})
                
                # Process each log record
                for log_record in scope_logs.get('logRecords', []):
                    # Extract timestamp
                    time_unix_nano = log_record.get('timeUnixNano', '0')
                    if isinstance(time_unix_nano, str):
                        time_unix_nano = int(time_unix_nano)
                    timestamp = time_unix_nano / 1_000_000_000 if time_unix_nano else time.time()
                    
                    # Extract trace/span IDs - convert from base64 to hex
                    trace_id_b64 = log_record.get('traceId', '')
                    span_id_b64 = log_record.get('spanId', '')
                    
                    trace_id = base64.b64decode(trace_id_b64).hex() if trace_id_b64 else ''
                    span_id = base64.b64decode(span_id_b64).hex() if span_id_b64 else ''
                    
                    # Extract message from body
                    body = log_record.get('body', {})
                    message = body.get('stringValue', '') if isinstance(body, dict) else str(body)
                    
                    # Extract severity
                    severity = log_record.get('severityText', 'INFO')
                    
                    # Build log entry
                    log_entry = {
                        'timestamp': timestamp,
                        'severity': severity,
                        'message': message,
                        'trace_id': trace_id,
                        'span_id': span_id,
                        'service_name': service_name,
                        'attributes': self.parse_attributes(log_record.get('attributes', [])),
                        'resource': resource_attrs,  # Store full resource context
                        'scope': {
                            'name': scope.get('name', ''),
                            'version': scope.get('version', '')
                        }
                    }
                    
                    logs.append(log_entry)
        
        return logs
    
    async def store_logs_otlp(self, otlp_data):
        """Store logs in OTLP format by parsing and delegating to store_logs"""
        logs = self.parse_otlp_logs(otlp_data)
        if logs:
            await self.store_logs(logs)
    
    async def store_log(self, log):
        """Store a single log (legacy wrapper)"""
        await self.store_logs([log])

    async def store_logs(self, logs):
        """Store multiple logs efficiently"""
        if not logs:
            return

        try:
            client = await self.get_client()
            pipe = client.pipeline()
            
            for log in logs:
                if 'log_id' not in log:
                    log['log_id'] = str(uuid.uuid4())
                    
                log_id = log['log_id']
                timestamp = log.get('timestamp', time.time())
                log['timestamp'] = timestamp
                
                # Store log content (compressed msgpack)
                log_key = f"log:{log_id}"
                packed_data = self._compress_for_storage(log)
                pipe.setex(log_key, self.ttl, packed_data)
                
                # Index by timestamp
                pipe.zadd('log_index', {log_id: timestamp})
                pipe.expire('log_index', self.ttl)
                
                trace_id = log.get('trace_id') or log.get('traceId')
                if trace_id:
                    trace_log_key = f"trace:{trace_id}:logs"
                    pipe.rpush(trace_log_key, log_id)
                    pipe.expire(trace_log_key, self.ttl)
            
            await pipe.execute()
        except Exception as e:
            print(f"Redis error in store_logs: {e}")

    async def get_logs(self, trace_id=None, limit=100):
        """Get logs, optionally filtered by trace_id"""
        try:
            client = await self.get_client()
            if trace_id:
                trace_log_key = f"trace:{trace_id}:logs"
                log_ids = await client.lrange(trace_log_key, 0, limit - 1)
            else:
                log_ids = await client.zrevrange('log_index', 0, limit - 1)
                
            # Decode IDs if they are bytes
            log_ids = [lid.decode('utf-8') if isinstance(lid, bytes) else lid for lid in log_ids]
            
            logs = []
            for log_id in log_ids:
                log_data = await client.get(f"log:{log_id}")
                if log_data:
                    logs.append(self._decompress_if_needed(log_data))
            
            return logs
        except Exception as e:
            print(f"Error getting logs: {e}")
            return []

    def parse_attributes(self, attrs_list):
        """Parse OTLP attributes list into a dict (reused from traces)"""
        if not attrs_list:
            return {}
        
        result = {}
        for attr in attrs_list:
            key = attr.get('key', '')
            value_obj = attr.get('value', {})
            
            # Extract the actual value
            if 'stringValue' in value_obj:
                result[key] = value_obj['stringValue']
            elif 'intValue' in value_obj:
                result[key] = value_obj['intValue']
            elif 'doubleValue' in value_obj:
                result[key] = value_obj['doubleValue']
            elif 'boolValue' in value_obj:
                result[key] = value_obj['boolValue']
            else:
                result[key] = str(value_obj)
        
        return result

    def extract_resource_attributes(self, resource):
        """Extract resource attributes from OTLP resource (reused from traces)"""
        if not resource:
            return {}
        
        attributes = resource.get('attributes', [])
        return self.parse_attributes(attributes)

    def _hash_dict(self, d):
        """Create a stable hash for a dictionary"""
        import hashlib
        sorted_items = sorted(d.items())
        s = json.dumps(sorted_items, sort_keys=True)
        return hashlib.md5(s.encode()).hexdigest()[:8]

    def parse_otlp_metrics(self, data):
        """Parse OTLP metrics format into structured datapoints"""
        datapoints = []
        
        # Support both camelCase and snake_case field names
        resource_metrics = data.get('resourceMetrics', data.get('resource_metrics', []))
        
        for resource_metric in resource_metrics:
            # Extract resource attributes
            resource = resource_metric.get('resource', {})
            resource_attrs = self.extract_resource_attributes(resource)
            
            scope_metrics = resource_metric.get('scopeMetrics', [])
            
            for scope_metric in scope_metrics:
                metrics = scope_metric.get('metrics', [])
                
                for metric in metrics:
                    name = metric.get('name')
                    unit = metric.get('unit', '')
                    description = metric.get('description', '')
                    
                    if not name:
                        continue
                    
                    # Determine metric type and extract datapoints
                    metric_type = 'unknown'
                    metric_datapoints = []
                    temporality = None
                    
                    # Gauge
                    if 'gauge' in metric:
                        metric_type = 'gauge'
                        gauge = metric['gauge']
                        metric_datapoints = gauge.get('dataPoints', [])
                    
                    # Sum (counter)
                    elif 'sum' in metric:
                        metric_type = 'sum'
                        sum_data = metric['sum']
                        metric_datapoints = sum_data.get('dataPoints', [])
                        temporality = sum_data.get('aggregationTemporality', 'CUMULATIVE')
                    
                    # Histogram
                    elif 'histogram' in metric:
                        metric_type = 'histogram'
                        histogram = metric['histogram']
                        metric_datapoints = histogram.get('dataPoints', [])
                        temporality = histogram.get('aggregationTemporality', 'CUMULATIVE')
                    
                    # Summary
                    elif 'summary' in metric:
                        metric_type = 'summary'
                        summary = metric['summary']
                        metric_datapoints = summary.get('dataPoints', [])
                    
                    # Process each datapoint
                    for dp in metric_datapoints:
                        # Parse attributes
                        dp_attrs = self.parse_attributes(dp.get('attributes', []))
                        
                        # Parse timestamp (nanoseconds to seconds)
                        time_unix_nano = dp.get('timeUnixNano', 0)
                        if isinstance(time_unix_nano, str):
                            time_unix_nano = int(time_unix_nano)
                        timestamp = time_unix_nano / 1_000_000_000 if time_unix_nano else time.time()
                        
                        # Extract value based on type
                        value = None
                        histogram_data = None
                        summary_data = None
                        
                        if metric_type == 'gauge':
                            if 'asInt' in dp:
                                value = dp['asInt']
                            elif 'asDouble' in dp:
                                value = dp['asDouble']
                        
                        elif metric_type == 'sum':
                            if 'asInt' in dp:
                                value = dp['asInt']
                            elif 'asDouble' in dp:
                                value = dp['asDouble']
                        
                        elif metric_type == 'histogram':
                            value = dp.get('sum', 0)
                            histogram_data = {
                                'count': dp.get('count', 0),
                                'sum': dp.get('sum', 0),
                                'bucketCounts': dp.get('bucketCounts', []),
                                'explicitBounds': dp.get('explicitBounds', [])
                            }
                        
                        elif metric_type == 'summary':
                            value = dp.get('sum', 0)
                            summary_data = {
                                'count': dp.get('count', 0),
                                'sum': dp.get('sum', 0),
                                'quantileValues': dp.get('quantileValues', [])
                            }
                        
                        # Extract exemplars
                        exemplars = []
                        for ex in dp.get('exemplars', []):
                            ex_time_nano = ex.get('timeUnixNano', 0)
                            if isinstance(ex_time_nano, str):
                                ex_time_nano = int(ex_time_nano)
                            ex_timestamp = ex_time_nano / 1_000_000_000 if ex_time_nano else timestamp
                            
                            ex_value = None
                            if 'asInt' in ex:
                                ex_value = ex['asInt']
                            elif 'asDouble' in ex:
                                ex_value = ex['asDouble']
                            
                            # Extract trace and span IDs from exemplar
                            trace_id = ex.get('traceId', '')
                            span_id = ex.get('spanId', '')
                            
                            # Convert bytes to hex if needed
                            if isinstance(trace_id, bytes):
                                trace_id = trace_id.hex()
                            if isinstance(span_id, bytes):
                                span_id = span_id.hex()
                            
                            exemplars.append({
                                'timestamp': ex_timestamp,
                                'value': ex_value,
                                'traceId': trace_id,
                                'spanId': span_id,
                                'filteredAttributes': self.parse_attributes(ex.get('filteredAttributes', []))
                            })
                        
                        # Create datapoint object
                        datapoint = {
                            'name': name,
                            'type': metric_type,
                            'unit': unit,
                            'description': description,
                            'temporality': temporality,
                            'resource': resource_attrs,
                            'attributes': dp_attrs,
                            'timestamp': timestamp,
                            'value': value,
                            'histogram': histogram_data,
                            'summary': summary_data,
                            'exemplars': exemplars
                        }
                        
                        datapoints.append(datapoint)
        
        return datapoints

    async def store_metric_datapoint(self, name, metric_type, unit, description, temporality, 
                                     resource, attributes, value, timestamp, 
                                     histogram=None, summary=None, exemplars=None):
        """Store a single OTLP metric datapoint"""
        try:
            client = await self.get_client()
            pipe = client.pipeline()
            
            # Create hashes for resource and attributes
            resource_hash = self._hash_dict(resource)
            attr_hash = self._hash_dict(attributes)
            
            # 1. Add to metric names set
            pipe.sadd('metrics:names', name)
            pipe.expire('metrics:names', self.ttl)
            
            # 2. Store metric metadata
            meta_key = f"metrics:meta:{name}"
            meta_data = {
                'type': metric_type,
                'unit': unit,
                'description': description,
                'temporality': temporality or 'N/A'
            }
            pipe.set(meta_key, orjson.dumps(meta_data))
            pipe.expire(meta_key, self.ttl)
            
            # 3. Store resource combinations
            resource_key = f"metrics:resources:{name}"
            pipe.sadd(resource_key, orjson.dumps(resource))
            pipe.expire(resource_key, self.ttl)
            
            # 3b. Store attribute combinations (Optimization for get_all_attributes)
            if attributes:
                attr_set_key = f"metrics:attributes:{name}"
                # Store as JSON for consistency
                pipe.sadd(attr_set_key, orjson.dumps(attributes, option=orjson.OPT_SORT_KEYS))
                pipe.expire(attr_set_key, self.ttl)
            
            # 4. Store time series data
            series_key = f"metrics:series:{name}:{resource_hash}:{attr_hash}"
            
            # Store datapoint with full context
            datapoint_data = {
                'resource': resource,
                'attributes': attributes,
                'value': value,
                'timestamp': timestamp,
                'histogram': histogram,
                'summary': summary
            }
            
            packed_dp = self._compress_for_storage(datapoint_data)
            pipe.zadd(series_key, {packed_dp: timestamp})
            pipe.expire(series_key, self.ttl)
            
            # 5. Store exemplars if present
            if exemplars:
                exemplar_key = f"metrics:exemplars:{name}:{resource_hash}:{attr_hash}"
                for ex in exemplars:
                    packed_ex = self._compress_for_storage(ex)
                    pipe.zadd(exemplar_key, {packed_ex: ex['timestamp']})
                pipe.expire(exemplar_key, self.ttl)
            
            await pipe.execute()
        except Exception as e:
            print(f"Error storing metric datapoint: {e}")

    async def store_metric(self, metric):
        """Store a single metric (legacy wrapper)"""
        await self.store_metrics([metric])

    async def store_metrics(self, metrics):
        """Store multiple metrics - supports both legacy and OTLP formats"""
        if not metrics:
            return

        try:
            # Check if this is OTLP format (support both camelCase and snake_case)
            if isinstance(metrics, dict) and ('resourceMetrics' in metrics or 'resource_metrics' in metrics):
                # Parse OTLP format
                datapoints = self.parse_otlp_metrics(metrics)
                
                # Store each datapoint
                for dp in datapoints:
                    await self.store_metric_datapoint(
                        name=dp['name'],
                        metric_type=dp['type'],
                        unit=dp['unit'],
                        description=dp['description'],
                        temporality=dp['temporality'],
                        resource=dp['resource'],
                        attributes=dp['attributes'],
                        value=dp['value'],
                        timestamp=dp['timestamp'],
                        histogram=dp['histogram'],
                        summary=dp['summary'],
                        exemplars=dp['exemplars']
                    )
                return
            
            # Legacy format handling
            client = await self.get_client()
            
            # Check cardinality first (optimization: check once per batch)
            current_count = await client.scard('metric_names')
            
            pipe = client.pipeline()
            
            for metric in metrics:
                name = metric.get('name')
                timestamp = metric.get('timestamp', time.time())
                
                if not name:
                    continue
                
                # Simple cardinality check - if we're over limit, we might drop new metrics
                # This is a loose check in batch mode for performance
                if current_count >= self.max_cardinality:
                    # We need to check if it exists, which is slow in a loop.
                    # For batch performance, we'll skip the strict per-item check here
                    # and rely on periodic cleanup or accept slight overage.
                    pass 
                    
                # Store in time-series sorted set
                metric_key = f"metric:{name}"
                # Use msgpack for metric data too
                metric_data = self._compress_for_storage(metric)
                
                # ZADD with binary data as member
                pipe.zadd(metric_key, {metric_data: timestamp})
                pipe.expire(metric_key, self.ttl)
                
                # Add to metric names index
                pipe.sadd('metric_names', name)
                pipe.expire('metric_names', self.ttl)
            
            await pipe.execute()
        except Exception as e:
            print(f"Redis error in store_metrics: {e}")

    @alru_cache(maxsize=1, ttl=10)
    async def get_metric_names(self, limit=None):
        """Get metric names from OTLP storage, with fallback to legacy"""
        client = await self.get_client()
        
        # Try OTLP format first
        otlp_names = list(await client.smembers('metrics:names'))
        if otlp_names:
            names = [n.decode('utf-8') if isinstance(n, bytes) else n for n in otlp_names]
            names.sort()
            if limit and limit > 0:
                return names[:limit]
            return names
        
        # Fallback to legacy format
        names = list(await client.smembers('metric_names'))
        # Decode names
        names = [n.decode('utf-8') if isinstance(n, bytes) else n for n in names]
        names.sort()
        
        if limit and limit > 0:
            return names[:limit]
        return names

    async def get_metric_metadata(self, name):
        """Get metadata for a specific metric"""
        try:
            client = await self.get_client()
            meta_key = f"metrics:meta:{name}"
            meta_data = await client.get(meta_key)
            
            if not meta_data:
                return {'type': 'unknown', 'unit': '', 'description': '', 'temporality': 'N/A'}
            
            return orjson.loads(meta_data)
        except Exception as e:
            print(f"Error getting metric metadata: {e}")
            return {'type': 'unknown', 'unit': '', 'description': '', 'temporality': 'N/A'}

    async def get_all_resources(self, metric_name):
        """Get all resource combinations for a metric"""
        try:
            client = await self.get_client()
            resource_key = f"metrics:resources:{metric_name}"
            resource_jsons = await client.smembers(resource_key)
            
            resources = []
            for rj in resource_jsons:
                if isinstance(rj, bytes):
                    resources.append(orjson.loads(rj))
                else:
                    resources.append(orjson.loads(rj.encode('utf-8')))
            
            return resources
        except Exception as e:
            print(f"Error getting resources: {e}")
            return []

    async def get_all_attributes(self, metric_name, resource_filter=None):
        """Get all attribute combinations for a metric, optionally filtered by resource"""
        try:
            client = await self.get_client()
            
            # Optimization: If no resource filter, use the pre-aggregated set
            if not resource_filter:
                attr_set_key = f"metrics:attributes:{metric_name}"
                # Check if key exists (it might not for old data)
                if await client.exists(attr_set_key):
                    attr_jsons = await client.smembers(attr_set_key)
                    return [orjson.loads(a) for a in attr_jsons]
            
            # Fallback to slow scan (existing logic) or if resource filter is present
            
            # Get all series keys for this metric
            pattern = f"metrics:series:{metric_name}:*"
            keys = []
            
            async for key in client.scan_iter(match=pattern):
                if isinstance(key, bytes):
                    keys.append(key.decode('utf-8'))
                else:
                    keys.append(key)
            
            # Extract unique attribute combinations
            attributes_set = set()
            
            for key in keys:
                # Get one datapoint from this series to extract attributes
                datapoints = await client.zrange(key, 0, 0)
                if datapoints:
                    dp = self._decompress_if_needed(datapoints[0])
                    
                    # Apply resource filter if provided
                    if resource_filter:
                        dp_resource = dp.get('resource', {})
                        # Check if all filter key-value pairs match
                        matches = all(
                            dp_resource.get(k) == v 
                            for k, v in resource_filter.items()
                        )
                        if not matches:
                            continue
                    
                    # Add attributes to set (as JSON string for uniqueness)
                    attrs = dp.get('attributes', {})
                    attributes_set.add(orjson.dumps(attrs, option=orjson.OPT_SORT_KEYS))
            
            # Convert back to list of dicts
            return [orjson.loads(a) for a in attributes_set]
        except Exception as e:
            print(f"Error getting attributes: {e}")
            return []

    async def get_metric_series(self, name, resource_filter=None, attr_filter=None, 
                               start_time=None, end_time=None):
        """Get metric series data with optional filters"""
        try:
            client = await self.get_client()
            
            # Default time range
            if start_time is None:
                start_time = time.time() - 600  # Last 10 minutes
            if end_time is None:
                end_time = time.time()
            
            # Get all series keys for this metric
            pattern = f"metrics:series:{name}:*"
            keys = []
            
            async for key in client.scan_iter(match=pattern):
                if isinstance(key, bytes):
                    keys.append(key.decode('utf-8'))
                else:
                    keys.append(key)
            
            # Collect matching series
            series_list = []
            
            for key in keys:
                # Get datapoints in time range
                datapoints_raw = await client.zrangebyscore(key, start_time, end_time)
                if not datapoints_raw:
                    continue
                
                # Decompress datapoints
                datapoints = [self._decompress_if_needed(dp) for dp in datapoints_raw]
                
                if not datapoints:
                    continue
                
                # Use first datapoint to get resource and attributes
                first_dp = datapoints[0]
                dp_resource = first_dp.get('resource', {})
                dp_attributes = first_dp.get('attributes', {})
                
                # Apply resource filter
                if resource_filter:
                    matches = all(
                        dp_resource.get(k) == v 
                        for k, v in resource_filter.items()
                    )
                    if not matches:
                        continue
                
                # Apply attribute filter
                if attr_filter:
                    matches = all(
                        dp_attributes.get(k) == v 
                        for k, v in attr_filter.items()
                    )
                    if not matches:
                        continue
                
                # Get exemplars for this series
                resource_hash = key.split(':')[3]
                attr_hash = key.split(':')[4]
                exemplar_key = f"metrics:exemplars:{name}:{resource_hash}:{attr_hash}"
                exemplars_raw = await client.zrangebyscore(exemplar_key, start_time, end_time)
                exemplars = [self._decompress_if_needed(ex) for ex in exemplars_raw] if exemplars_raw else []
                
                # Format series with normalized numeric values
                series = {
                    'resource': dp_resource,
                    'attributes': dp_attributes,
                    'datapoints': [
                        self._normalize_datapoint(dp)
                        for dp in datapoints
                    ],
                    'exemplars': exemplars
                }
                
                series_list.append(series)
            
            return series_list
        except Exception as e:
            print(f"Error getting metric series: {e}")
            return []
    
    async def get_cardinality_stats(self):
        """Get metric cardinality statistics"""
        client = await self.get_client()
        dropped_count_str = await client.get('metric_dropped_count')
        dropped_names = await client.smembers('metric_dropped_names')
        
        return {
            'current': await client.scard('metric_names'),
            'max': self.max_cardinality,
            'dropped_count': int(dropped_count_str) if dropped_count_str else 0,
            'dropped_names': [n.decode('utf-8') for n in dropped_names]
        }

    async def get_metric_data(self, name, start_time, end_time):
        """Get metric data points for a time range"""
        client = await self.get_client()
        metric_key = f"metric:{name}"
        data = await client.zrangebyscore(metric_key, start_time, end_time)
        return [self._decompress_if_needed(d) for d in data]

    async def get_service_graph(self, limit=500):
        """Build service dependency graph from recent traces with metrics"""
        client = await self.get_client()
        cache_key = f"service_graph_cache_v2:{limit}"
        cached_graph = await client.get(cache_key)
        if cached_graph:
            return orjson.loads(cached_graph)

        # Get catalog for node metrics
        catalog_services = await self.get_service_catalog()
        service_metrics = {s['name']: s for s in catalog_services}
        
        nodes = {} # name -> {type, metrics}
        
        # Initialize nodes from catalog
        for s in catalog_services:
            nodes[s['name']] = {'type': 'service', 'metrics': s}

        trace_ids = await self.get_recent_traces(limit)
        edges = {}  # (source, target) -> {count, durations}
        
        # Helper to get attribute value
        def _get_span_attr_value(span, key_to_find):
            attributes = span.get('attributes', [])
            if isinstance(attributes, list):
                for attr in attributes:
                    if attr.get('key') == key_to_find:
                        val = attr.get('value', {})
                        if 'stringValue' in val: return val['stringValue']
                        if 'intValue' in val: return val['intValue']
                        if 'boolValue' in val: return val['boolValue']
                        return str(val)
            elif isinstance(attributes, dict):
                return attributes.get(key_to_find)
            return None

        for trace_id in trace_ids:
            spans = await self.get_trace_spans(trace_id)
            if not spans:
                continue
            
            span_map = {s.get('spanId', s.get('span_id')): s for s in spans}
            
            for span in spans:
                service = span.get('serviceName', 'unknown')
                if service and service != 'unknown':
                    if service not in nodes:
                        nodes[service] = {'type': 'service', 'metrics': {}}
                
                # Calculate duration
                start = int(span.get('startTimeUnixNano', span.get('start_time', 0)))
                end = int(span.get('endTimeUnixNano', span.get('end_time', 0)))
                duration_ms = (end - start) / 1_000_000 if end > start else 0

                # 1. Check for External Calls
                target_node = None
                node_type = None
                
                db_system = _get_span_attr_value(span, 'db.system')
                if db_system:
                    db_name = _get_span_attr_value(span, 'db.name') or db_system
                    target_node = db_name
                    node_type = 'database'
                    
                messaging_system = _get_span_attr_value(span, 'messaging.system')
                if messaging_system:
                    dest = _get_span_attr_value(span, 'messaging.destination') or messaging_system
                    target_node = dest
                    node_type = 'messaging'

                if target_node:
                    if target_node not in nodes:
                        nodes[target_node] = {'type': node_type, 'metrics': {}}
                    
                    key = (service, target_node)
                    if key not in edges:
                        edges[key] = {'count': 0, 'durations': []}
                    edges[key]['count'] += 1
                    edges[key]['durations'].append(duration_ms)

                # 2. Check for Service-to-Service Calls
                parent_id = span.get('parentSpanId', span.get('parent_span_id'))
                if parent_id and parent_id in span_map:
                    parent = span_map[parent_id]
                    parent_service = parent.get('serviceName', 'unknown')
                    
                    if parent_service != service and parent_service != 'unknown' and service != 'unknown':
                        key = (parent_service, service)
                        if key not in edges:
                            edges[key] = {'count': 0, 'durations': []}
                        edges[key]['count'] += 1
                        edges[key]['durations'].append(duration_ms)

    
        # Format for frontend
        graph_nodes = []
        for name, data in nodes.items():
            node_entry = {
                'id': name, 
                'label': name,
                'type': data.get('type', 'service'),
                'metrics': data.get('metrics', {})
            }
            graph_nodes.append(node_entry)
        
        graph_edges = []
        for (source, target), data in edges.items():
            # Calculate p95
            durations = sorted(data['durations'])
            p95 = 0
            if durations:
                idx = int(len(durations) * 0.95)
                p95 = durations[idx]
            
            graph_edges.append({
                'source': source,
                'target': target,
                'value': data['count'],
                'p95': round(p95, 2),
                'req_rate': round(data['count'] / 60, 2) # Approx req/sec based on recent window (assuming ~1 min?) - actually just raw count for now, frontend can interpret
            })
        
        result = {
            'nodes': graph_nodes,
            'edges': graph_edges
        }
        
        await client.setex(cache_key, 5, orjson.dumps(result).decode('utf-8'))
        return result

    @alru_cache(maxsize=1, ttl=5)
    async def get_service_catalog(self):
        """Get list of all services with their stats and RED metrics"""
        # Get all recent spans to extract service information
        span_ids = await self.get_recent_spans(1000)
        
        services = {}  # service_name -> {span_count, trace_count, first_seen, last_seen, trace_ids}
        
        for span_id in span_ids:
            span_data = await self.get_span_details(span_id)
            if not span_data:
                continue
                
            service_name = span_data.get('service_name', 'unknown')
            trace_id = span_data.get('trace_id')
            start_time = span_data.get('start_time', 0)
            
            if service_name not in services:
                services[service_name] = {
                    'name': service_name,
                    'span_count': 0,
                    'trace_count': 0,
                    'first_seen': start_time,
                    'last_seen': start_time,
                    'trace_ids': set()
                }
            
            services[service_name]['span_count'] += 1
            services[service_name]['trace_ids'].add(trace_id)
            services[service_name]['first_seen'] = min(services[service_name]['first_seen'], start_time)
            services[service_name]['last_seen'] = max(services[service_name]['last_seen'], start_time)
        
        # Convert to list and calculate trace counts
        result = []
        for service_name, data in services.items():
            service_info = {
                'name': data['name'],
                'span_count': data['span_count'],
                'trace_count': len(data['trace_ids']),
                'first_seen': data['first_seen'],
                'last_seen': data['last_seen']
            }
            
            # Fetch RED metrics for this service
            red_metrics = await self._get_service_red_metrics(service_name)
            service_info.update(red_metrics)
            
            result.append(service_info)
        
        return result
    
    async def _get_service_red_metrics(self, service_name):
        """Get RED (Rate, Errors, Duration) metrics for a service"""
        red = {
            'rate': None,
            'error_rate': None,
            'duration_p50': None,
            'duration_p95': None,
            'duration_p99': None
        }
        
        try:
            all_metrics = await self.get_metric_names()
            duration_metric = "traces.span.metrics.duration"
            calls_metric = "traces.span.metrics.calls"
            
            # Check if metrics exist (optimization)
            if duration_metric not in all_metrics:
                return red
                
            # Use resource filter for service name
            resource_filter = {'service.name': service_name}
            end_time = time.time()
            start_time = end_time - 60
            
            # Fetch Duration Data
            duration_series = await self.get_metric_series(
                duration_metric, 
                resource_filter=resource_filter,
                start_time=start_time,
                end_time=end_time
            )
            
            # Fetch Calls Data
            calls_series = []
            if calls_metric in all_metrics:
                calls_series = await self.get_metric_series(
                    calls_metric, 
                    resource_filter=resource_filter,
                    start_time=start_time,
                    end_time=end_time
                )
            
            if not duration_series:
                return red
            
            # Group by 15-second time buckets to aggregate metrics
            BUCKET_SIZE = 15  # seconds
            grouped_by_time = {}
            
            for series in duration_series:
                for point in series['datapoints']:
                    ts = point['timestamp']
                    bucket_ts = int(ts / BUCKET_SIZE) * BUCKET_SIZE
                    if bucket_ts not in grouped_by_time:
                        grouped_by_time[bucket_ts] = {'count': 0, 'buckets': []}
                    
                    hist = point.get('histogram', {})
                    if hist:
                        grouped_by_time[bucket_ts]['count'] += hist.get('count', 0)
                        # Store bucket counts and bounds for aggregation
                        grouped_by_time[bucket_ts]['buckets'].append({
                            'counts': hist.get('bucketCounts', []),
                            'bounds': hist.get('explicitBounds', [])
                        })
            
            if len(grouped_by_time) >= 1:
                sorted_times = sorted(grouped_by_time.keys())
                latest_ts = sorted_times[-1]
                latest = grouped_by_time[latest_ts]
                
                # Calculate rate from aggregated counts
                if len(grouped_by_time) >= 2:
                    previous_ts = sorted_times[-2]
                    previous = grouped_by_time[previous_ts]
                    count_latest = latest['count']
                    count_prev = previous['count']
                    time_diff = latest_ts - previous_ts
                    
                    if time_diff > 0 and count_latest > count_prev:
                        import math
                        red['rate'] = math.ceil((count_latest - count_prev) / time_diff)
                else:
                    import math
                    red['rate'] = math.ceil(latest['count'] / BUCKET_SIZE)
                
                # Calculate error rate from calls metric
                if calls_series:
                    total_calls = 0
                    error_calls = 0
                    
                    for series in calls_series:
                        # Check status code in attributes (OTLP standard is http.response.status_code or status.code)
                        attrs = series.get('attributes', {})
                        status_code = attrs.get('status.code') or attrs.get('http.response.status_code')
                        
                        for point in series['datapoints']:
                            value = point.get('value', 0)
                            total_calls += value
                            
                            # Check for error status
                            if status_code == 'STATUS_CODE_ERROR' or status_code == 'ERROR' or (isinstance(status_code, int) and status_code >= 400):
                                error_calls += value
                    
                    if total_calls > 0:
                        red['error_rate'] = round((error_calls / total_calls) * 100, 2)
                
                # Calculate percentiles from the latest aggregated buckets
                # We need to sum up bucket counts across all series for the latest timestamp
                latest_buckets_list = latest['buckets']
                if latest_buckets_list:
                    # Assume all histograms have same bounds (safe assumption for same metric)
                    # Use bounds from first bucket entry
                    bounds = latest_buckets_list[0]['bounds']
                    if bounds:
                        num_buckets = len(bounds) + 1 # +1 for +Inf
                        aggregated_counts = [0] * num_buckets
                        total_count = 0
                        
                        for entry in latest_buckets_list:
                            counts = entry['counts']
                            # Ensure counts match expected length
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
                                
                                # Use bound if available, else it's +Inf
                                bound_ms = bounds[i] if i < len(bounds) else None
                                if bound_ms is None:
                                    continue
                                
                                if red['duration_p50'] is None and percentile >= 50:
                                    red['duration_p50'] = round((prev_bound + bound_ms) / 2, 2)
                                if red['duration_p95'] is None and percentile >= 95:
                                    red['duration_p95'] = round((prev_bound + bound_ms) / 2, 2)
                                if red['duration_p99'] is None and percentile >= 99:
                                    red['duration_p99'] = round((prev_bound + bound_ms) / 2, 2)
                                
                                prev_bound = bound_ms
        
        except Exception as e:
            print(f"Error fetching RED metrics for {service_name}: {e}", flush=True)
        
        return red

    async def get_stats(self):
        """Get overall stats including cardinality"""
        client = await self.get_client()
        cardinality = await self.get_cardinality_stats()
        return {
            'traces': await client.zcard('trace_index'),
            'spans': await client.zcard('span_index'),
            'logs': await client.zcard('log_index'),
            'metrics': cardinality['current'],
            'metrics_max': cardinality['max'],
            'metrics_dropped': cardinality['dropped_count']
        }
