"""
Pydantic models for TinyOlly API request/response validation and OpenAPI schema generation.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


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
    storage: Literal["connected", "disconnected"]
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "storage": "connected"
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
    label_count: int = Field(..., description="Number of label dimension keys")
    services: List[str] = Field(default=[], description="List of service names emitting this metric")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "http.server.duration",
                "type": "histogram",
                "unit": "ms",
                "description": "HTTP request duration",
                "resource_count": 3,
                "attribute_combinations": 10,
                "services": ["frontend", "backend"]
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
    """Detailed admin statistics including DB and performance metrics"""
    telemetry: Dict[str, int] = Field(..., description="Telemetry data counts (traces, spans, logs, metrics)")
    db: Dict[str, Any] = Field(..., description="SQLite database size and page stats")
    cardinality: Dict[str, float] = Field(..., description="Metric cardinality stats (percent_used is fractional)")
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

