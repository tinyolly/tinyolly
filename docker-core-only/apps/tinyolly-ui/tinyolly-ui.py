"""
TinyOlly - A minimal observability backend with visualization
Receives traces, metrics, and logs, stores them in Redis with TTL,
and provides a web UI for visualization and correlation.
Optimized with ORJSON, uvloop, and batch operations.
"""

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import json
import os
import time
from typing import Optional, Dict, Any, List
from tinyolly_redis_storage import Storage
import uvloop
import asyncio

# Install uvloop policy for faster event loop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

app = FastAPI(
    title="TinyOlly", 
    version="2.0.0",
    description="Lightweight OpenTelemetry-native observability backend for logs, metrics & traces",
    default_response_class=ORJSONResponse,  # Use faster JSON serialization
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
# Ingestion Endpoints
# ============================================

@app.post('/v1/traces', tags=["Ingestion"])
async def ingest_traces(request: Request):
    """Accept traces in OTLP JSON format (OpenTelemetry Protocol)"""
    # Check content length
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    
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
    
    return {'status': 'ok'}

@app.post('/v1/logs', tags=["Ingestion"])
async def ingest_logs(request: Request):
    """Accept logs in OTLP JSON format (OpenTelemetry Protocol)"""
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    
    # Handle array or single log
    logs = data if isinstance(data, list) else [data]
    
    # Filter valid logs
    valid_logs = [log for log in logs if isinstance(log, dict)]
    
    if valid_logs:
        await storage.store_logs(valid_logs)
    
    return {'status': 'ok'}

@app.post('/v1/metrics', tags=["Ingestion"])
async def ingest_metrics(request: Request):
    """Accept metrics in OTLP JSON format (OpenTelemetry Protocol)"""
    # Validate payload size (limit to 5MB)
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')

    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    
    # Check if this is OTLP format
    if isinstance(data, dict) and 'resourceMetrics' in data:
        # OTLP format - store directly
        await storage.store_metrics(data)
    else:
        # Legacy format - handle array or single metric
        metrics = data if isinstance(data, list) else [data]
        
        # Filter valid metrics
        valid_metrics = [m for m in metrics if isinstance(m, dict) and 'name' in m]
        
        if valid_metrics:
            await storage.store_metrics(valid_metrics)
    
    return {'status': 'ok'}

# ============================================
# Query Endpoints
# ============================================

@app.get('/api/traces', tags=["Traces"])
async def get_traces(limit: int = Query(default=100, description="Maximum number of traces to return")):
    """Get list of recent traces with summaries"""
    # Get recent trace IDs from index
    trace_ids = await storage.get_recent_traces(limit)
    
    traces = []
    for trace_id in trace_ids:
        trace_data = await storage.get_trace_summary(trace_id)
        if trace_data:
            traces.append(trace_data)
    
    return traces

@app.get('/api/traces/{trace_id}', tags=["Traces"])
async def get_trace(trace_id: str):
    """Get complete trace details with all spans and correlated logs"""
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

@app.get('/api/spans', tags=["Spans"])
async def get_spans(
    limit: int = Query(default=100, description="Maximum number of spans to return"),
    service: Optional[str] = Query(default=None, description="Filter by service name")
):
    """Get list of recent spans with optional service filter"""
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

@app.get('/api/logs', tags=["Logs"])
async def get_logs(
    trace_id: Optional[str] = Query(default=None, description="Filter by trace ID for correlation"),
    limit: int = Query(default=100, description="Maximum number of logs to return")
):
    """Get recent logs with optional trace ID filter for correlation"""
    logs = await storage.get_logs(trace_id, limit)
    return logs

@app.get('/api/logs/stream', tags=["Logs"])
async def stream_logs():
    """Server-Sent Events (SSE) stream for real-time log monitoring"""
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
                
            except Exception as e:
                print(f"Error in log stream: {e}")
                await asyncio.sleep(5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.get('/api/metrics', tags=["Metrics"])
async def get_metrics(limit: Optional[int] = Query(default=None, description="Maximum number of metrics to return")):
    """Get list of all metrics with OpenTelemetry metadata (type, unit, description, resources)"""
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

@app.get('/api/metrics/{name}', tags=["Metrics"])
async def get_metric_detail(
    name: str,
    start: float = Query(default=None, description="Start time (Unix timestamp)"),
    end: float = Query(default=None, description="End time (Unix timestamp)")
):
    """Get detailed time series data for a metric including resources, attributes, and exemplars (trace correlation)"""
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

@app.get('/api/metrics/query', tags=["Metrics"])
async def query_metrics(
    name: str = Query(..., description="Metric name"),
    start: float = Query(default=None, description="Start time (Unix timestamp)"),
    end: float = Query(default=None, description="End time (Unix timestamp)"),
    request: Request = None
):
    """Query metrics with resource and attribute filters (use resource.* and attribute.* query params)"""
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

@app.get('/api/metrics/{name}/resources', tags=["Metrics"])
async def get_metric_resources(name: str):
    """Get all unique resource attribute combinations for a metric"""
    resources = await storage.get_all_resources(name)
    return resources

@app.get('/api/metrics/{name}/attributes', tags=["Metrics"])
async def get_metric_attributes(
    name: str,
    request: Request = None
):
    """Get all unique metric attribute combinations, optionally filtered by resource (use resource.* query params)"""
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

@app.get('/api/service-map', tags=["Services"])
async def get_service_map(limit: int = Query(default=500, description="Maximum number of traces to analyze")):
    """Get service dependency graph showing connections between services"""
    graph = await storage.get_service_graph(limit)
    return graph

@app.get('/api/service-catalog', tags=["Services"])
async def get_service_catalog():
    """Get service catalog with RED metrics (Rate, Errors, Duration)"""
    services = await storage.get_service_catalog()
    return services

@app.get('/api/stats', tags=["Services"])
async def get_stats():
    """Get overall system statistics (traces, spans, logs, metrics counts)"""
    return await storage.get_stats()

# ============================================
# Web UI Routes
# ============================================

@app.get('/', response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
async def index(request: Request):
    """Serve the main web UI dashboard"""
    deployment_env = os.getenv('DEPLOYMENT_ENV', 'unknown')
    return templates.TemplateResponse('tinyolly.html', {
        'request': request,
        'deployment_env': deployment_env
    })

@app.get('/health', tags=["System"])
async def health():
    """Health check endpoint for monitoring and load balancers"""
    if await storage.is_connected():
        return {'status': 'healthy', 'redis': 'connected'}
    else:
        raise HTTPException(status_code=503, detail={'status': 'unhealthy', 'redis': 'disconnected'})

if __name__ == '__main__':
    import uvicorn
    print("Starting TinyOlly UI...")
    print("✓ HTTP mode: http://localhost:5002")
    # uvloop is already installed via policy at top of file
    uvicorn.run(app, host='0.0.0.0', port=5002)
