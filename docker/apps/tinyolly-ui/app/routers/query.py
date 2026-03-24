"""Query endpoints for traces, spans, logs, and metrics"""

import json
import time
import asyncio
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse

from models import (
    TraceDetail, ErrorResponse, MetricMetadata, MetricDetail,
    MetricQueryResult
)
from ..dependencies import get_storage
from tinyolly_common import Storage

router = APIRouter(prefix="/api", tags=["Traces", "Spans", "Logs", "Metrics"])


@router.get(
    '/traces',
    response_model=List[Dict[str, Any]],
    operation_id="get_traces",
    summary="Get recent traces",
    responses={
        200: {"description": "List of trace summaries"}
    }
)
async def get_traces(
    limit: int = Query(default=1000, le=5000, description="Maximum number of traces to return (max 5000)"),
    storage: Storage = Depends(get_storage)
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


@router.get(
    '/traces/{trace_id}',
    response_model=TraceDetail,
    operation_id="get_trace_by_id",
    summary="Get trace details",
    responses={
        200: {"description": "Complete trace with all spans"},
        404: {"model": ErrorResponse, "description": "Trace not found"}
    }
)
async def get_trace(
    trace_id: str,
    storage: Storage = Depends(get_storage)
):
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


@router.get(
    '/spans',
    response_model=List[Dict[str, Any]],
    operation_id="get_spans",
    summary="Get recent spans",
    responses={
        200: {"description": "List of span details"}
    }
)
async def get_spans(
    limit: int = Query(default=1000, le=5000, description="Maximum number of spans to return (max 5000)"),
    service: Optional[str] = Query(default=None, description="Filter by service name"),
    storage: Storage = Depends(get_storage)
):
    """
    Get list of recent spans with optional service filter.
    
    Returns individual span details including service name, operation, duration, and attributes.
    Can be filtered by service name for service-specific queries.
    """
    # Get recent span IDs from index
    max_span_ids = limit * 3 if service else limit
    span_ids = await storage.get_recent_spans(max_span_ids)
    
    if not span_ids:
        return []
    
    # Use batch operation to fetch all span details at once (much faster)
    all_spans = await storage.get_spans_details_batch(span_ids)
    
    # Filter by service if requested
    if service:
        all_spans = [s for s in all_spans if s.get('service_name') == service]
    
    # Return up to limit
    return all_spans[:limit]


@router.get(
    '/logs',
    response_model=List[Dict[str, Any]],
    operation_id="get_logs",
    summary="Get recent logs",
    responses={
        200: {"description": "List of log entries"}
    }
)
async def get_logs(
    trace_id: Optional[str] = Query(default=None, description="Filter by trace ID for correlation"),
    limit: int = Query(default=1000, le=5000, description="Maximum number of logs to return (max 5000)"),
    storage: Storage = Depends(get_storage)
):
    """
    Get recent logs with optional trace ID filter for correlation.
    
    Returns log entries with full OpenTelemetry log data including timestamp, severity, body, 
    and attributes. When trace_id is provided, returns only logs associated with that trace 
    for distributed trace correlation.
    """
    logs = await storage.get_logs(trace_id, limit)
    return logs


@router.get(
    '/logs/stream',
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
async def stream_logs(storage: Storage = Depends(get_storage)):
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
    import logging
    logger = logging.getLogger(__name__)
    
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


@router.get(
    '/metrics',
    response_model=List[MetricMetadata],
    operation_id="get_metrics",
    summary="Get all metrics",
    responses={
        200: {"description": "List of all available metrics with metadata"}
    }
)
async def get_metrics(
    limit: Optional[int] = Query(default=None, le=5000, description="Maximum number of metrics to return (max 5000)"),
    storage: Storage = Depends(get_storage)
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

        # Extract unique service names from resources
        services = list(set(
            r.get('service.name') for r in resources
            if r.get('service.name')
        ))

        return {
            'name': name,
            'type': metadata.get('type') or 'unknown',
            'unit': metadata.get('unit', ''),
            'description': metadata.get('description', ''),
            'resource_count': len(resources),
            'attribute_combinations': len(attributes),
            'label_count': len(attributes[0].keys()) if attributes else 0,
            'services': services
        }

    # Fetch all metrics in parallel
    metrics_list = await asyncio.gather(*(fetch_metric_details(name) for name in names))
    
    return metrics_list


@router.get(
    '/metrics/{name}',
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
    end: float = Query(default=None, description="End time (Unix timestamp). Default: now"),
    storage: Storage = Depends(get_storage)
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
    start_time = start if start is not None else time.time() - 3600
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


@router.get(
    '/metrics/query',
    response_model=MetricQueryResult,
    operation_id="query_metrics",
    summary="Query metrics with filters",
    responses={
        200: {"description": "Filtered metric time series data"}
    }
)
async def query_metrics(
    request: Request,
    name: str = Query(..., description="Metric name"),
    start: float = Query(default=None, description="Start time (Unix timestamp). Default: 10 minutes ago"),
    end: float = Query(default=None, description="End time (Unix timestamp). Default: now"),
    storage: Storage = Depends(get_storage)
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
    start_time = start if start is not None else time.time() - 3600
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


@router.get(
    '/metrics/{name}/resources',
    response_model=List[Dict[str, Any]],
    operation_id="get_metric_resources",
    summary="Get metric resources",
    responses={
        200: {"description": "List of unique resource attribute combinations"}
    }
)
async def get_metric_resources(
    name: str,
    storage: Storage = Depends(get_storage)
):
    """
    Get all unique resource attribute combinations for a metric.
    
    Returns all distinct resource attribute sets (service.name, host.name, etc.) 
    that have emitted this metric. Useful for discovering what resources are 
    reporting a particular metric.
    """
    resources = await storage.get_all_resources(name)
    return resources


@router.get(
    '/metrics/{name}/attributes',
    response_model=List[Dict[str, Any]],
    operation_id="get_metric_attributes",
    summary="Get metric attributes",
    responses={
        200: {"description": "List of unique metric attribute combinations"}
    }
)
async def get_metric_attributes(
    request: Request,
    name: str,
    storage: Storage = Depends(get_storage)
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
