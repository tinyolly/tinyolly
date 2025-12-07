"""
TinyOlly - A minimal observability backend with visualization
Receives traces, metrics, and logs, stores them in Redis with TTL,
and provides a web UI for visualization and correlation.
Optimized with ORJSON, uvloop, and batch operations.
"""

from fastapi import FastAPI, Request, HTTPException, Query, status, APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse, ORJSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
import json
import os
import time
import logging
import sys
from typing import Optional, Dict, Any, List, Literal, Set
from tinyolly_common import Storage
import uvloop
import asyncio

# Configure logging with stdout handler
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # Ensure logs go to stdout
    ]
)
logger = logging.getLogger(__name__)

# Install uvloop policy for faster event loop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Configure OpenTelemetry metrics
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

# Set up OTLP metric exporter
metric_exporter = OTLPMetricExporter(
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://localhost:5001/v1/metrics")
)

# Configure metric reader with 60s export interval
metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
meter_provider = MeterProvider(metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)

# Create meter for tinyolly-ui
meter = metrics.get_meter("tinyolly-ui")

# Create metrics
request_counter = meter.create_counter(
    name="http.server.requests",
    description="Total HTTP requests",
    unit="1"
)

error_counter = meter.create_counter(
    name="http.server.errors",
    description="Total HTTP errors",
    unit="1"
)

response_time_histogram = meter.create_histogram(
    name="http.server.duration",
    description="HTTP request duration",
    unit="ms"
)

ingestion_counter = meter.create_counter(
    name="tinyolly.ingestion.count",
    description="Total telemetry ingestion operations",
    unit="1"
)

storage_operations_counter = meter.create_counter(
    name="tinyolly.storage.operations",
    description="Storage operations by type",
    unit="1"
)

# ============================================
# Pydantic Models for OpenAPI Schema
# ============================================

class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str = Field(..., description="Error message describing what went wrong")
    
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Trace not found"
            }
        }

class HealthResponse(BaseModel):
    """Health check response"""
    status: Literal["healthy", "unhealthy"]
    redis: Literal["connected", "disconnected"]
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "redis": "connected"
            }
        }

class IngestResponse(BaseModel):
    """Response for ingestion endpoints"""
    status: Literal["ok"]
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok"
            }
        }

class TraceSpan(BaseModel):
    """Individual span in a trace"""
    span_id: Optional[str] = Field(None, description="Unique span identifier")
    trace_id: Optional[str] = Field(None, description="Trace ID this span belongs to")
    parent_span_id: Optional[str] = Field(None, description="Parent span ID for hierarchy")
    name: Optional[str] = Field(None, description="Span operation name")
    kind: Optional[int] = Field(None, description="Span kind (internal, server, client, etc.)")
    startTimeUnixNano: Optional[int] = Field(None, description="Start time in nanoseconds")
    endTimeUnixNano: Optional[int] = Field(None, description="End time in nanoseconds")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Span attributes")
    status: Optional[Dict[str, Any]] = Field(None, description="Span status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "span_id": "abc123",
                "trace_id": "trace-xyz",
                "name": "GET /api/users",
                "kind": 2,
                "startTimeUnixNano": 1638360000000000000,
                "endTimeUnixNano": 1638360001000000000,
                "attributes": {"http.method": "GET", "http.status_code": 200},
                "status": {"code": 0}
            }
        }

class TraceSummary(BaseModel):
    """Trace summary for list view"""
    trace_id: str = Field(..., description="Unique trace identifier")
    root_service: Optional[str] = Field(None, description="Root service name")
    root_operation: Optional[str] = Field(None, description="Root operation name")
    duration: Optional[float] = Field(None, description="Total trace duration in milliseconds")
    span_count: Optional[int] = Field(None, description="Number of spans in trace")
    start_time: Optional[float] = Field(None, description="Trace start time (Unix timestamp)")
    has_errors: Optional[bool] = Field(None, description="Whether trace contains errors")

class TraceDetail(BaseModel):
    """Complete trace with all spans"""
    trace_id: str = Field(..., description="Unique trace identifier")
    spans: List[Dict[str, Any]] = Field(..., description="All spans in the trace")
    span_count: int = Field(..., description="Total number of spans")
    
    class Config:
        json_schema_extra = {
            "example": {
                "trace_id": "trace-xyz",
                "spans": [{"span_id": "abc123", "name": "GET /api/users"}],
                "span_count": 1
            }
        }

class SpanDetail(BaseModel):
    """Detailed span information"""
    span_id: str
    trace_id: str
    service_name: Optional[str] = None
    operation: Optional[str] = None
    duration: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None

class LogEntry(BaseModel):
    """Log entry"""
    log_id: Optional[str] = Field(None, description="Unique log identifier")
    timestamp: Optional[float] = Field(None, description="Log timestamp (Unix)")
    trace_id: Optional[str] = Field(None, description="Associated trace ID for correlation")
    span_id: Optional[str] = Field(None, description="Associated span ID for correlation")
    severity: Optional[str] = Field(None, description="Log severity level")
    body: Optional[str] = Field(None, description="Log message body")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Additional log attributes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "log_id": "log-123",
                "timestamp": 1638360000.0,
                "trace_id": "trace-xyz",
                "severity": "INFO",
                "body": "User request processed successfully",
                "attributes": {"user_id": "user-456"}
            }
        }

class MetricMetadata(BaseModel):
    """Metric metadata"""
    name: str = Field(..., description="Metric name")
    type: str = Field(..., description="Metric type (gauge, counter, histogram, etc.)")
    unit: str = Field(default="", description="Metric unit")
    description: str = Field(default="", description="Metric description")
    resource_count: int = Field(..., description="Number of unique resource combinations")
    attribute_combinations: int = Field(..., description="Number of unique attribute combinations")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "http.server.duration",
                "type": "histogram",
                "unit": "ms",
                "description": "HTTP request duration",
                "resource_count": 3,
                "attribute_combinations": 10
            }
        }

class MetricTimeSeries(BaseModel):
    """Time series data for a metric"""
    resources: Dict[str, Any] = Field(..., description="Resource attributes")
    attributes: Dict[str, Any] = Field(..., description="Metric labels/attributes")
    data_points: List[Dict[str, Any]] = Field(..., description="Time series data points")

class MetricDetail(BaseModel):
    """Detailed metric information with time series"""
    name: str = Field(..., description="Metric name")
    type: str = Field(..., description="Metric type")
    unit: str = Field(default="", description="Metric unit")
    description: str = Field(default="", description="Metric description")
    series: List[Dict[str, Any]] = Field(..., description="Time series data")

class MetricQueryResult(BaseModel):
    """Result of metric query with filters"""
    name: str
    type: str
    unit: str
    description: str
    series: List[Dict[str, Any]]
    filters: Dict[str, Dict[str, Any]] = Field(..., description="Applied filters")

class ServiceNode(BaseModel):
    """Service node in service map"""
    name: str = Field(..., description="Service name")
    request_count: int = Field(..., description="Total requests")
    error_count: int = Field(..., description="Total errors")

class ServiceEdge(BaseModel):
    """Edge between services in service map"""
    source: str = Field(..., description="Source service")
    target: str = Field(..., description="Target service")
    request_count: int = Field(..., description="Number of requests")

class ServiceMap(BaseModel):
    """Service dependency graph"""
    nodes: List[Dict[str, Any]] = Field(..., description="Service nodes")
    edges: List[Dict[str, Any]] = Field(..., description="Service connections")

class ServiceCatalogEntry(BaseModel):
    """Service catalog entry with RED metrics"""
    name: str = Field(..., description="Service name")
    request_rate: float = Field(..., description="Requests per second")
    error_rate: float = Field(..., description="Error rate percentage")
    avg_duration: float = Field(..., description="Average request duration in ms")
    p95_duration: Optional[float] = Field(None, description="95th percentile duration")
    p99_duration: Optional[float] = Field(None, description="99th percentile duration")

class StatsResponse(BaseModel):
    """Overall system statistics"""
    trace_count: int = Field(..., description="Total number of traces")
    span_count: int = Field(..., description="Total number of spans")
    log_count: int = Field(..., description="Total number of logs")
    metric_count: int = Field(..., description="Total number of unique metrics")
    service_count: Optional[int] = Field(None, description="Number of services")

class AdminStatsResponse(BaseModel):
    """Detailed admin statistics including Redis and performance metrics"""
    telemetry: Dict[str, int] = Field(..., description="Telemetry data counts (traces, spans, logs, metrics)")
    redis: Dict[str, Any] = Field(..., description="Redis memory and connection info")
    cardinality: Dict[str, int] = Field(..., description="Metric cardinality stats")
    uptime: Optional[str] = Field(None, description="TinyOlly uptime")

class AlertRule(BaseModel):
    """Alert rule configuration"""
    name: str = Field(..., description="Alert rule name")
    type: Literal["span_error", "metric_threshold"] = Field(..., description="Alert type")
    enabled: bool = Field(default=True, description="Whether alert is enabled")
    webhook_url: str = Field(..., description="Webhook URL to send alerts to")
    # For span_error type
    service_filter: Optional[str] = Field(None, description="Filter by service name (span_error only)")
    # For metric_threshold type
    metric_name: Optional[str] = Field(None, description="Metric name to monitor (metric_threshold only)")
    threshold: Optional[float] = Field(None, description="Threshold value (metric_threshold only)")
    comparison: Optional[Literal["gt", "lt", "eq"]] = Field(None, description="Comparison operator (metric_threshold only)")

class AlertConfig(BaseModel):
    """Alert configuration response"""
    rules: List[AlertRule] = Field(default_factory=list, description="Configured alert rules")

app = FastAPI(
    title="TinyOlly",
    version="2.0.0",
    description="""
# TinyOlly - Lightweight OpenTelemetry Observability Platform

TinyOlly is a lightweight OpenTelemetry-native observability backend built from scratch
to visualize and correlate logs, metrics, and traces. Perfect for local development.

## Features

* 📊 **Traces** - Distributed tracing with span visualization
* 📝 **Logs** - Structured logging with trace correlation
* 📈 **Metrics** - Time-series metrics with full OTLP support
* 🗺️ **Service Map** - Auto-generated service dependency graphs
* 🔍 **Service Catalog** - RED metrics (Rate, Errors, Duration)

## OpenTelemetry Native

All data is stored and returned in standard OpenTelemetry format, ensuring
compatibility with OTLP exporters and OpenTelemetry SDKs.
    """,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "TinyOlly Project",
        "url": "https://github.com/tinyolly/tinyolly",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=[
        {
            "name": "Ingestion",
            "description": "OTLP endpoints for ingesting telemetry data (traces, logs, metrics)"
        },
        {
            "name": "Traces",
            "description": "Query and retrieve trace data"
        },
        {
            "name": "Spans",
            "description": "Query and retrieve individual span data"
        },
        {
            "name": "Logs",
            "description": "Query and retrieve log entries with trace correlation"
        },
        {
            "name": "Metrics",
            "description": "Query and retrieve time-series metrics data"
        },
        {
            "name": "Services",
            "description": "Service catalog, service map, and RED metrics"
        },
        {
            "name": "System",
            "description": "Health checks and system status"
        }
    ]
)

# Add custom metrics middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Track request metrics for all HTTP endpoints"""
    start_time = time.time()

    # Track request
    request_counter.add(1, {
        "method": request.method,
        "endpoint": request.url.path
    })

    try:
        response = await call_next(request)

        # Track response time
        duration_ms = (time.time() - start_time) * 1000
        response_time_histogram.record(duration_ms, {
            "method": request.method,
            "endpoint": request.url.path,
            "status": response.status_code
        })

        # Track errors
        if response.status_code >= 400:
            error_counter.add(1, {
                "method": request.method,
                "endpoint": request.url.path,
                "status": response.status_code
            })

        return response
    except Exception as e:
        # Track exceptions
        error_counter.add(1, {
            "method": request.method,
            "endpoint": request.url.path,
            "error_type": type(e).__name__
        })
        raise

# Add CORS middleware
# Default to localhost only for security, can be customized via environment variable
# Example: CORS_ORIGINS="http://localhost:*,http://127.0.0.1:*,https://example.com"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:*,http://127.0.0.1:*")
allowed_origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add GZip compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Initialize storage
storage = Storage()

# ============================================
# WebSocket Connection Manager
# ============================================

class ConnectionManager:
    """Manages WebSocket connections for real-time updates.

    Handles multiple concurrent WebSocket connections and broadcasts
    updates to all connected clients.
    """

    def __init__(self):
        """Initialize connection manager with empty connections set."""
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection.

        Args:
            websocket (WebSocket): WebSocket connection to register
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from active connections.

        Args:
            websocket (WebSocket): WebSocket connection to remove
        """
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients.

        Args:
            message (dict): Message to broadcast (will be JSON-serialized)
        """
        if not self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# ============================================
# Alert Manager
# ============================================

class AlertManager:
    """Manages alert rules and webhook notifications.

    Handles alerting for span errors and metric threshold breaches.
    """

    def __init__(self):
        """Initialize alert manager with empty rules."""
        self.rules: List[AlertRule] = []
        self._load_rules_from_env()

    def _load_rules_from_env(self):
        """Load alert rules from environment variables.

        Format: ALERT_RULES='[{"name":"...", "type":"...", "webhook_url":"...", ...}]'
        """
        rules_json = os.getenv("ALERT_RULES", "[]")
        try:
            rules_data = json.loads(rules_json)
            for rule_data in rules_data:
                self.rules.append(AlertRule(**rule_data))
            if self.rules:
                logger.info(f"Loaded {len(self.rules)} alert rules from environment")
        except Exception as e:
            logger.error(f"Error loading alert rules: {e}")

    def add_rule(self, rule: AlertRule):
        """Add a new alert rule.

        Args:
            rule (AlertRule): Alert rule to add
        """
        self.rules.append(rule)
        logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str):
        """Remove an alert rule by name.

        Args:
            rule_name (str): Name of rule to remove
        """
        self.rules = [r for r in self.rules if r.name != rule_name]
        logger.info(f"Removed alert rule: {rule_name}")

    async def check_span_error(self, span: dict):
        """Check if span has error and trigger alerts.

        Args:
            span (dict): Span data to check
        """
        # Check if span has error status
        status = span.get('status', {})
        if status.get('code') == 2:  # ERROR status code in OTLP
            for rule in self.rules:
                if not rule.enabled or rule.type != "span_error":
                    continue

                # Apply service filter if specified
                if rule.service_filter and span.get('serviceName') != rule.service_filter:
                    continue

                # Trigger alert
                await self._send_webhook(rule, {
                    "alert_type": "span_error",
                    "rule_name": rule.name,
                    "span_id": span.get('spanId'),
                    "trace_id": span.get('traceId'),
                    "service": span.get('serviceName'),
                    "operation": span.get('name'),
                    "error_message": status.get('message', 'Unknown error'),
                    "timestamp": span.get('startTimeUnixNano')
                })

    async def check_metric_threshold(self, metric_name: str, value: float):
        """Check if metric exceeds threshold and trigger alerts.

        Args:
            metric_name (str): Name of the metric
            value (float): Current metric value
        """
        for rule in self.rules:
            if not rule.enabled or rule.type != "metric_threshold":
                continue

            if rule.metric_name != metric_name:
                continue

            # Check threshold
            triggered = False
            if rule.comparison == "gt" and value > rule.threshold:
                triggered = True
            elif rule.comparison == "lt" and value < rule.threshold:
                triggered = True
            elif rule.comparison == "eq" and value == rule.threshold:
                triggered = True

            if triggered:
                await self._send_webhook(rule, {
                    "alert_type": "metric_threshold",
                    "rule_name": rule.name,
                    "metric_name": metric_name,
                    "current_value": value,
                    "threshold": rule.threshold,
                    "comparison": rule.comparison,
                    "timestamp": int(time.time() * 1e9)
                })

    async def _send_webhook(self, rule: AlertRule, payload: dict):
        """Send webhook notification.

        Args:
            rule (AlertRule): Alert rule that triggered
            payload (dict): Alert payload to send
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rule.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status >= 400:
                        logger.error(f"Webhook failed: {response.status} for rule {rule.name}")
                    else:
                        logger.info(f"Alert sent for rule {rule.name}")
        except Exception as e:
            logger.error(f"Error sending webhook for rule {rule.name}: {e}")

alert_manager = AlertManager()

# ============================================
# API Version Routers
# ============================================

# API Versioning Strategy:
# - /v1/* - OTLP ingestion endpoints (already versioned)
# - /api/* - Legacy query endpoints (backward compatible, no version prefix)
# - /api/v1/* - New v1 query endpoints (recommended for new integrations)
# - /api/v2/* - Future v2 endpoints for breaking changes
#
# Migration Path:
# 1. Keep /api/* endpoints for backward compatibility
# 2. Add new features to /api/v1/*
# 3. Deprecate /api/* in favor of /api/v1/* over time
# 4. Eventually introduce /api/v2/* for breaking changes

# Create API v1 router
api_v1_router = APIRouter(prefix="/api/v1", tags=["API v1"])

# Note: Legacy /api/* endpoints remain for backward compatibility
# All new development should use versioned /api/v1/* endpoints

# ============================================
# Ingestion Endpoints
# ============================================

@app.post(
    '/v1/traces',
    tags=["Ingestion"],
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    operation_id="ingest_traces",
    summary="Ingest traces",
    responses={
        200: {"description": "Traces successfully ingested"},
        400: {"model": ErrorResponse, "description": "Invalid JSON payload"},
        413: {"model": ErrorResponse, "description": "Payload too large (max 5MB)"}
    }
)
async def ingest_traces(request: Request):
    """
    Accept traces in OTLP JSON format (OpenTelemetry Protocol).
    
    Supports both full OTLP format with `resourceSpans` or simplified format with `spans` array.
    Maximum payload size is 5MB.
    
    **OTLP Format Example:**
    ```json
    {
      "resourceSpans": [{
        "scopeSpans": [{
          "spans": [{
            "traceId": "abc123",
            "spanId": "span456",
            "name": "GET /api/users"
          }]
        }]
      }]
    }
    ```
    """
    # Check content length
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}')

    spans_to_store = []
    
    if 'resourceSpans' in data:
        for resource_span in data['resourceSpans']:
            for scope_span in resource_span.get('scopeSpans', []):
                for span in scope_span.get('spans', []):
                    spans_to_store.append(span)
    elif 'spans' in data:
        spans_to_store = data['spans']
    else:
        spans_to_store = [data]
    
    if spans_to_store:
        await storage.store_spans(spans_to_store)

        # Track ingestion metrics
        ingestion_counter.add(len(spans_to_store), {"type": "spans"})
        storage_operations_counter.add(1, {"operation": "store_spans", "count": len(spans_to_store)})

        # Check for span errors and trigger alerts
        for span in spans_to_store:
            await alert_manager.check_span_error(span)

    return {'status': 'ok'}

@app.post(
    '/v1/logs',
    tags=["Ingestion"],
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    operation_id="ingest_logs",
    summary="Ingest logs",
    responses={
        200: {"description": "Logs successfully ingested"},
        400: {"model": ErrorResponse, "description": "Invalid JSON payload"},
        413: {"model": ErrorResponse, "description": "Payload too large (max 5MB)"}
    }
)
async def ingest_logs(request: Request):
    """
    Accept logs in OTLP JSON format (OpenTelemetry Protocol).
    
    Supports both array of logs or single log entry.
    Maximum payload size is 5MB.
    
    **Example:**
    ```json
    [{
      "timestamp": 1638360000,
      "traceId": "trace-xyz",
      "spanId": "span-abc",
      "severityText": "INFO",
      "body": "User logged in",
      "attributes": {"user_id": "123"}
    }]
    ```
    """
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}')

    # Handle array or single log
    logs = data if isinstance(data, list) else [data]
    
    # Filter valid logs
    valid_logs = [log for log in logs if isinstance(log, dict)]

    if valid_logs:
        await storage.store_logs(valid_logs)

        # Track ingestion metrics
        ingestion_counter.add(len(valid_logs), {"type": "logs"})
        storage_operations_counter.add(1, {"operation": "store_logs", "count": len(valid_logs)})

    return {'status': 'ok'}

@app.post(
    '/v1/metrics',
    tags=["Ingestion"],
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    operation_id="ingest_metrics",
    summary="Ingest metrics",
    responses={
        200: {"description": "Metrics successfully ingested"},
        400: {"model": ErrorResponse, "description": "Invalid JSON payload"},
        413: {"model": ErrorResponse, "description": "Payload too large (max 5MB)"}
    }
)
async def ingest_metrics(request: Request):
    """
    Accept metrics in OTLP JSON format (OpenTelemetry Protocol).
    
    Supports both full OTLP format with `resourceMetrics` or simplified legacy format.
    Maximum payload size is 5MB.
    
    **OTLP Format Example:**
    ```json
    {
      "resourceMetrics": [{
        "scopeMetrics": [{
          "metrics": [{
            "name": "http.server.duration",
            "unit": "ms",
            "histogram": {...}
          }]
        }]
      }]
    }
    ```
    """
    # Validate payload size (limit to 5MB)
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}')

    # Check if this is OTLP format
    if isinstance(data, dict) and 'resourceMetrics' in data:
        # OTLP format - store directly
        await storage.store_metrics(data)

        # Count metrics in OTLP format
        metric_count = 0
        for resource_metric in data.get('resourceMetrics', []):
            for scope_metric in resource_metric.get('scopeMetrics', []):
                metric_count += len(scope_metric.get('metrics', []))

        # Track ingestion metrics
        ingestion_counter.add(metric_count, {"type": "metrics"})
        storage_operations_counter.add(1, {"operation": "store_metrics", "count": metric_count})
    else:
        # Legacy format - handle array or single metric
        metrics_data = data if isinstance(data, list) else [data]

        # Filter valid metrics
        valid_metrics = [m for m in metrics_data if isinstance(m, dict) and 'name' in m]

        if valid_metrics:
            await storage.store_metrics(valid_metrics)

            # Track ingestion metrics
            ingestion_counter.add(len(valid_metrics), {"type": "metrics"})
            storage_operations_counter.add(1, {"operation": "store_metrics", "count": len(valid_metrics)})

    return {'status': 'ok'}

# ============================================
# Query Endpoints
# ============================================

@app.get(
    '/api/traces',
    tags=["Traces"],
    response_model=List[Dict[str, Any]],
    operation_id="get_traces",
    summary="Get recent traces",
    responses={
        200: {"description": "List of trace summaries"}
    }
)
async def get_traces(
    limit: int = Query(default=100, le=1000, description="Maximum number of traces to return (max 1000)")
):
    """
    Get list of recent traces with summaries.
    
    Returns trace metadata including root service, operation name, duration, span count, 
    and error status. Results are sorted by most recent first.
    """
    # Get recent trace IDs from index
    trace_ids = await storage.get_recent_traces(limit)
    
    traces = []
    for trace_id in trace_ids:
        trace_data = await storage.get_trace_summary(trace_id)
        if trace_data:
            traces.append(trace_data)
    
    return traces

@app.get(
    '/api/traces/{trace_id}',
    tags=["Traces"],
    response_model=TraceDetail,
    operation_id="get_trace_by_id",
    summary="Get trace details",
    responses={
        200: {"description": "Complete trace with all spans"},
        404: {"model": ErrorResponse, "description": "Trace not found"}
    }
)
async def get_trace(trace_id: str):
    """
    Get complete trace details with all spans and correlated logs.
    
    Returns full trace information including all spans sorted by start time,
    with full OpenTelemetry span data (attributes, status, events, links, etc.).
    """
    spans = await storage.get_trace_spans(trace_id)
    
    if not spans:
        raise HTTPException(status_code=404, detail='Trace not found')
    
    # Sort spans by start time
    spans.sort(key=lambda s: s.get('startTimeUnixNano', s.get('start_time', 0)))
    
    return {
        'trace_id': trace_id,
        'spans': spans,
        'span_count': len(spans)
    }

@app.get(
    '/api/spans',
    tags=["Spans"],
    response_model=List[Dict[str, Any]],
    operation_id="get_spans",
    summary="Get recent spans",
    responses={
        200: {"description": "List of span details"}
    }
)
async def get_spans(
    limit: int = Query(default=100, le=1000, description="Maximum number of spans to return (max 1000)"),
    service: Optional[str] = Query(default=None, description="Filter by service name")
):
    """
    Get list of recent spans with optional service filter.
    
    Returns individual span details including service name, operation, duration, and attributes.
    Can be filtered by service name for service-specific queries.
    """
    # Get recent span IDs from index
    span_ids = await storage.get_recent_spans(limit * 3 if service else limit)  # Get more if filtering
    
    spans = []
    for span_id in span_ids:
        span_data = await storage.get_span_details(span_id)
        if span_data:
            # Filter by service if requested
            if service and span_data.get('service_name') != service:
                continue
            spans.append(span_data)
            # Stop once we have enough
            if len(spans) >= limit:
                break
    
    return spans

@app.get(
    '/api/logs',
    tags=["Logs"],
    response_model=List[Dict[str, Any]],
    operation_id="get_logs",
    summary="Get recent logs",
    responses={
        200: {"description": "List of log entries"}
    }
)
async def get_logs(
    trace_id: Optional[str] = Query(default=None, description="Filter by trace ID for correlation"),
    limit: int = Query(default=100, le=1000, description="Maximum number of logs to return (max 1000)")
):
    """
    Get recent logs with optional trace ID filter for correlation.
    
    Returns log entries with full OpenTelemetry log data including timestamp, severity, body, 
    and attributes. When trace_id is provided, returns only logs associated with that trace 
    for distributed trace correlation.
    """
    logs = await storage.get_logs(trace_id, limit)
    return logs

@app.get(
    '/api/logs/stream',
    tags=["Logs"],
    operation_id="stream_logs",
    summary="Stream logs in real-time",
    responses={
        200: {
            "description": "Server-Sent Events stream of log entries",
            "content": {
                "text/event-stream": {
                    "example": "data: {\"log_id\": \"123\", \"body\": \"User logged in\"}\n\n"
                }
            }
        }
    }
)
async def stream_logs():
    """
    Server-Sent Events (SSE) stream for real-time log monitoring.
    
    Opens a persistent connection that streams new log entries as they arrive.
    Perfect for live log tailing and real-time monitoring dashboards.
    
    **Usage Example:**
    ```javascript
    const eventSource = new EventSource('/api/logs/stream');
    eventSource.onmessage = (event) => {
      const log = JSON.parse(event.data);
      console.log(log);
    };
    ```
    """
    async def event_generator():
        last_check = time.time()
        sent_log_ids = set()
        
        while True:
            try:
                # Get recent logs
                logs = await storage.get_logs(None, 10)
                
                # Send only new logs
                for log in logs:
                    log_id = log.get('log_id')
                    if log_id and log_id not in sent_log_ids:
                        sent_log_ids.add(log_id)
                        # Keep set size manageable
                        if len(sent_log_ids) > 1000:
                            sent_log_ids.clear()
                        
                        yield f"data: {json.dumps(log)}\n\n"
                
                # Wait before next check
                await asyncio.sleep(2)

            except asyncio.CancelledError:
                # Client disconnected, stop streaming
                break
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error serializing log data: {e}")
                await asyncio.sleep(2)
            except Exception as e:
                # Catch-all for storage errors or unexpected issues
                # Keep connection alive but log the error
                logger.error(f"Error in log stream: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.get(
    '/api/metrics',
    tags=["Metrics"],
    response_model=List[MetricMetadata],
    operation_id="get_metrics",
    summary="Get all metrics",
    responses={
        200: {"description": "List of all available metrics with metadata"}
    }
)
async def get_metrics(
    limit: Optional[int] = Query(default=None, le=1000, description="Maximum number of metrics to return (max 1000)")
):
    """
    Get list of all metrics with OpenTelemetry metadata.
    
    Returns metric metadata including name, type (gauge, counter, histogram, etc.), 
    unit, description, and cardinality information (number of unique resource and 
    attribute combinations).
    """
    names = await storage.get_metric_names(limit=limit)
    
    async def fetch_metric_details(name):
        # Fetch all details for a single metric in parallel
        metadata, resources, attributes = await asyncio.gather(
            storage.get_metric_metadata(name),
            storage.get_all_resources(name),
            storage.get_all_attributes(name)
        )
        
        return {
            'name': name,
            'type': metadata.get('type') or 'unknown',
            'unit': metadata.get('unit', ''),
            'description': metadata.get('description', ''),
            'resource_count': len(resources),
            'attribute_combinations': len(attributes)
        }

    # Fetch all metrics in parallel
    metrics_list = await asyncio.gather(*(fetch_metric_details(name) for name in names))
    
    return metrics_list

@app.get(
    '/api/metrics/{name}',
    tags=["Metrics"],
    response_model=MetricDetail,
    operation_id="get_metric_detail",
    summary="Get metric time series",
    responses={
        200: {"description": "Metric time series data with all resources and attributes"}
    }
)
async def get_metric_detail(
    name: str,
    start: float = Query(default=None, description="Start time (Unix timestamp). Default: 10 minutes ago"),
    end: float = Query(default=None, description="End time (Unix timestamp). Default: now")
):
    """
    Get detailed time series data for a metric.
    
    Returns complete time series including resources, attributes, and exemplars for trace 
    correlation. Each series represents a unique combination of resource attributes and 
    metric labels.
    
    **Time Range:**
    - Default: Last 10 minutes
    - Custom: Specify `start` and `end` Unix timestamps
    """
    start_time = start if start is not None else time.time() - 600
    end_time = end if end is not None else time.time()
    
    # Get metadata
    metadata = await storage.get_metric_metadata(name)
    
    # Get all series for this metric
    series = await storage.get_metric_series(name, None, None, start_time, end_time)
    
    return {
        'name': name,
        'type': metadata.get('type', 'unknown'),
        'unit': metadata.get('unit', ''),
        'description': metadata.get('description', ''),
        'series': series
    }

@app.get(
    '/api/metrics/query',
    tags=["Metrics"],
    response_model=MetricQueryResult,
    operation_id="query_metrics",
    summary="Query metrics with filters",
    responses={
        200: {"description": "Filtered metric time series data"}
    }
)
async def query_metrics(
    name: str = Query(..., description="Metric name"),
    start: float = Query(default=None, description="Start time (Unix timestamp). Default: 10 minutes ago"),
    end: float = Query(default=None, description="End time (Unix timestamp). Default: now"),
    request: Request = None
):
    """
    Query metrics with resource and attribute filters.
    
    Filters are specified using query parameters with special prefixes:
    - `resource.*` - Filter by resource attributes (e.g., `resource.service.name=my-service`)
    - `attribute.*` - Filter by metric labels (e.g., `attribute.http.method=GET`)
    
    **Example:**
    ```
    GET /api/metrics/query?name=http.server.duration&resource.service.name=frontend&attribute.http.method=GET
    ```
    
    Returns only time series matching ALL specified filters.
    """
    start_time = start if start is not None else time.time() - 600
    end_time = end if end is not None else time.time()
    
    # Parse resource and attribute filters from query params
    resource_filter = {}
    attr_filter = {}
    
    if request:
        for param, value in request.query_params.items():
            if param.startswith('resource.'):
                key = param.replace('resource.', '')
                resource_filter[key] = value
            elif param.startswith('attribute.'):
                key = param.replace('attribute.', '')
                attr_filter[key] = value
    
    # Get metadata
    metadata = await storage.get_metric_metadata(name)
    
    # Get filtered series
    series = await storage.get_metric_series(
        name, 
        resource_filter if resource_filter else None,
        attr_filter if attr_filter else None,
        start_time, 
        end_time
    )
    
    return {
        'name': name,
        'type': metadata.get('type', 'unknown'),
        'unit': metadata.get('unit', ''),
        'description': metadata.get('description', ''),
        'series': series,
        'filters': {
            'resource': resource_filter,
            'attributes': attr_filter
        }
    }

@app.get(
    '/api/metrics/{name}/resources',
    tags=["Metrics"],
    response_model=List[Dict[str, Any]],
    operation_id="get_metric_resources",
    summary="Get metric resources",
    responses={
        200: {"description": "List of unique resource attribute combinations"}
    }
)
async def get_metric_resources(name: str):
    """
    Get all unique resource attribute combinations for a metric.
    
    Returns all distinct resource attribute sets (service.name, host.name, etc.) 
    that have emitted this metric. Useful for discovering what resources are 
    reporting a particular metric.
    """
    resources = await storage.get_all_resources(name)
    return resources

@app.get(
    '/api/metrics/{name}/attributes',
    tags=["Metrics"],
    response_model=List[Dict[str, Any]],
    operation_id="get_metric_attributes",
    summary="Get metric attributes",
    responses={
        200: {"description": "List of unique metric attribute combinations"}
    }
)
async def get_metric_attributes(
    name: str,
    request: Request = None
):
    """
    Get all unique metric attribute combinations (labels).
    
    Returns all distinct metric label combinations for this metric.
    Can be optionally filtered by resource using `resource.*` query parameters.
    
    **Example:**
    ```
    GET /api/metrics/http.server.duration/attributes?resource.service.name=frontend
    ```
    
    This helps discover what label combinations exist and manage cardinality.
    """
    # Parse resource filters from query params
    resource_filter = {}
    
    if request:
        for param, value in request.query_params.items():
            if param.startswith('resource.'):
                key = param.replace('resource.', '')
                resource_filter[key] = value
    
    attributes = await storage.get_all_attributes(
        name, 
        resource_filter if resource_filter else None
    )
    return attributes

@app.get(
    '/api/service-map',
    tags=["Services"],
    response_model=ServiceMap,
    operation_id="get_service_map",
    summary="Get service dependency graph",
    responses={
        200: {"description": "Service dependency graph with nodes and edges"}
    }
)
async def get_service_map(
    limit: int = Query(default=500, le=5000, description="Maximum number of traces to analyze (max 5000)")
):
    """
    Get service dependency graph showing connections between services.
    
    Analyzes recent traces to build a directed graph of service-to-service 
    communication patterns. Returns nodes (services) and edges (calls between services)
    with request counts and error rates.
    
    Perfect for visualizing microservice architectures and understanding dependencies.
    """
    graph = await storage.get_service_graph(limit)
    return graph

@app.get(
    '/api/service-catalog',
    tags=["Services"],
    response_model=List[Dict[str, Any]],
    operation_id="get_service_catalog",
    summary="Get service catalog with RED metrics",
    responses={
        200: {"description": "Service catalog with Rate, Errors, Duration metrics"}
    }
)
async def get_service_catalog():
    """
    Get service catalog with RED metrics (Rate, Errors, Duration).
    
    Returns all services discovered from traces with their golden signals:
    - **Rate**: Requests per second
    - **Errors**: Error rate percentage
    - **Duration**: Average, P95, and P99 latency
    
    Essential for service health monitoring and SLO tracking.
    """
    services = await storage.get_service_catalog()
    return services

@app.get(
    '/api/stats',
    tags=["Services"],
    response_model=Dict[str, Any],
    operation_id="get_stats",
    summary="Get system statistics",
    responses={
        200: {"description": "Overall telemetry data statistics"}
    }
)
async def get_stats():
    """
    Get overall system statistics.
    
    Returns aggregate counts for all telemetry data types:
    - Total traces
    - Total spans
    - Total logs
    - Total unique metrics
    - Total services
    
    Useful for monitoring TinyOlly's data volume and health.
    """
    return await storage.get_stats()

# ============================================
# API v1 Versioned Endpoints
# ============================================

@api_v1_router.get(
    '/traces',
    response_model=List[Dict[str, Any]],
    operation_id="get_traces_v1",
    summary="Get recent traces (v1)",
    description="Get list of recent traces. This is the v1 API endpoint."
)
async def get_traces_v1(
    limit: int = Query(default=100, le=1000, description="Maximum number of traces to return (max 1000)")
):
    """Get list of recent traces (v1 endpoint)."""
    trace_ids = await storage.get_recent_traces(limit)
    traces = []
    for trace_id in trace_ids:
        summary = await storage.get_trace_summary(trace_id)
        if summary:
            traces.append(summary)
    return traces

@api_v1_router.get(
    '/stats',
    response_model=StatsResponse,
    operation_id="get_stats_v1",
    summary="Get system statistics (v1)"
)
async def get_stats_v1():
    """Get overall system statistics (v1 endpoint)."""
    stats = await storage.get_stats()
    return {
        'trace_count': stats.get('traces', 0),
        'span_count': stats.get('spans', 0),
        'log_count': stats.get('logs', 0),
        'metric_count': stats.get('metrics', 0),
        'service_count': None
    }

# Include the v1 router
app.include_router(api_v1_router)

# ============================================
# Web UI Routes
# ============================================

@app.get(
    '/',
    response_class=HTMLResponse,
    tags=["UI"],
    include_in_schema=False,
    operation_id="index"
)
async def index(request: Request):
    """Serve the main web UI dashboard"""
    deployment_env = os.getenv('DEPLOYMENT_ENV', 'unknown')
    return templates.TemplateResponse('tinyolly.html', {
        'request': request,
        'deployment_env': deployment_env
    })

@app.get(
    '/admin/stats',
    tags=["System"],
    response_model=AdminStatsResponse,
    operation_id="admin_stats",
    summary="Get detailed system statistics",
    description="""
    Get comprehensive TinyOlly performance and health metrics:

    - **Telemetry counts**: Traces, spans, logs, metrics
    - **Redis memory usage**: Current, peak, RSS
    - **Metric cardinality**: Current vs max, dropped count
    - **Connection stats**: Total connections, commands processed

    Useful for monitoring TinyOlly's resource usage and performance.
    """
)
async def admin_stats():
    """Get detailed admin statistics including Redis memory and performance metrics"""
    stats = await storage.get_admin_stats()

    # Add uptime calculation
    import psutil
    import datetime
    process = psutil.Process()
    uptime_seconds = time.time() - process.create_time()
    uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))
    stats['uptime'] = uptime_str

    return stats

@app.get(
    '/admin/alerts',
    tags=["System"],
    response_model=AlertConfig,
    operation_id="get_alerts",
    summary="Get alert configuration"
)
async def get_alerts():
    """Get all configured alert rules."""
    return AlertConfig(rules=alert_manager.rules)

@app.post(
    '/admin/alerts',
    tags=["System"],
    response_model=AlertRule,
    operation_id="create_alert",
    summary="Create alert rule"
)
async def create_alert(rule: AlertRule):
    """Create a new alert rule.

    **Span Error Alert Example:**
    ```json
    {
        "name": "API Errors",
        "type": "span_error",
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/...",
        "service_filter": "api-service"
    }
    ```

    **Metric Threshold Alert Example:**
    ```json
    {
        "name": "High CPU",
        "type": "metric_threshold",
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/...",
        "metric_name": "system.cpu.usage",
        "threshold": 80.0,
        "comparison": "gt"
    }
    ```
    """
    alert_manager.add_rule(rule)
    return rule

@app.delete(
    '/admin/alerts/{rule_name}',
    tags=["System"],
    operation_id="delete_alert",
    summary="Delete alert rule"
)
async def delete_alert(rule_name: str):
    """Delete an alert rule by name."""
    alert_manager.remove_rule(rule_name)
    return {"status": "ok", "message": f"Alert rule '{rule_name}' deleted"}

@app.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket):
    """WebSocket endpoint for real-time telemetry updates.

    Provides live updates for traces, logs, metrics, and stats without polling.
    Clients connect once and receive push notifications for new data.

    **Message Format:**
    ```json
    {
        "type": "stats" | "trace" | "log" | "metric",
        "data": {...}
    }
    ```

    **Usage Example (JavaScript):**
    ```javascript
    const ws = new WebSocket('ws://localhost:5002/ws/updates');
    ws.onmessage = (event) => {
        const update = JSON.parse(event.data);
        console.log(`Received ${update.type}:`, update.data);
    };
    ```
    """
    await manager.connect(websocket)
    try:
        # Send initial stats
        stats = await storage.get_stats()
        await websocket.send_json({
            "type": "stats",
            "data": stats
        })

        # Keep connection alive and send periodic updates
        while True:
            try:
                # Wait for client messages (ping/pong)
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send stats update every 30 seconds
                stats = await storage.get_stats()
                await websocket.send_json({
                    "type": "stats",
                    "data": stats
                })
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        manager.disconnect(websocket)

@app.get(
    '/health',
    tags=["System"],
    response_model=HealthResponse,
    operation_id="health_check",
    summary="Health check",
    responses={
        200: {
            "model": HealthResponse,
            "description": "Service is healthy"
        },
        503: {
            "model": HealthResponse,
            "description": "Service is unhealthy - Redis disconnected"
        }
    }
)
async def health():
    """
    Health check endpoint for monitoring and load balancers.

    Returns HTTP 200 when healthy, HTTP 503 when unhealthy.
    Checks Redis connectivity to ensure the backend can store and retrieve data.

    Use this endpoint for:
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Monitoring system uptime checks
    """
    if await storage.is_connected():
        return {'status': 'healthy', 'redis': 'connected'}
    else:
        raise HTTPException(
            status_code=503,
            detail={'status': 'unhealthy', 'redis': 'disconnected'}
        )

if __name__ == '__main__':
    import uvicorn
    # Port 5002 is the internal container port
    # Docker maps this to 5005 externally (see docker-compose-tinyolly-core.yml)
    # Kubernetes uses port 5002 directly (see k8s/tinyolly-ui.yaml)
    port = int(os.getenv('PORT', 5002))
    logger.info("Starting TinyOlly UI...")
    logger.info(f"✓ HTTP mode: http://0.0.0.0:{port}")
    # uvloop is already installed via policy at top of file
    uvicorn.run(app, host='0.0.0.0', port=port)
