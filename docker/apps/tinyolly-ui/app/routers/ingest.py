"""OTLP ingestion endpoints"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from models import ErrorResponse, IngestResponse

from tinyolly_common import Storage

from ..core.request_limits import read_json_body
from ..core.telemetry import get_metrics
from ..dependencies import get_alert_manager, get_storage
from ..managers.alerts import AlertManager

router = APIRouter(prefix="/v1", tags=["Ingestion"])

# Get metrics
_metrics = None


def get_ingestion_metrics():
    """Get metrics for ingestion endpoints"""
    global _metrics
    if _metrics is None:
        _metrics = get_metrics()
    return _metrics


@router.post(
    '/traces',
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
async def ingest_traces(
    request: Request,
    storage: Storage = Depends(get_storage),
    alert_manager: AlertManager = Depends(get_alert_manager)
):
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
    metrics = get_ingestion_metrics()
    
    try:
        data = await read_json_body(request)
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}') from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}') from e

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
        metrics["ingestion_counter"].add(len(spans_to_store), {"type": "spans"})
        metrics["storage_operations_counter"].add(1, {"operation": "store_spans", "count": len(spans_to_store)})

        # Check for span errors and trigger alerts
        for span in spans_to_store:
            await alert_manager.check_span_error(span)

    return {'status': 'ok'}


@router.post(
    '/logs',
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
async def ingest_logs(
    request: Request,
    storage: Storage = Depends(get_storage)
):
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
    metrics = get_ingestion_metrics()
    
    try:
        data = await read_json_body(request)
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}') from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}') from e

    # Handle array or single log
    logs = data if isinstance(data, list) else [data]
    
    # Filter valid logs
    valid_logs = [log for log in logs if isinstance(log, dict)]

    if valid_logs:
        await storage.store_logs(valid_logs)

        # Track ingestion metrics
        metrics["ingestion_counter"].add(len(valid_logs), {"type": "logs"})
        metrics["storage_operations_counter"].add(1, {"operation": "store_logs", "count": len(valid_logs)})

    return {'status': 'ok'}


@router.post(
    '/metrics',
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
async def ingest_metrics(
    request: Request,
    storage: Storage = Depends(get_storage)
):
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
    metrics = get_ingestion_metrics()
    
    try:
        data = await read_json_body(request)
        if not data:
            raise HTTPException(status_code=400, detail='Invalid JSON')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {str(e)}') from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid request body: {str(e)}') from e

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
        metrics["ingestion_counter"].add(metric_count, {"type": "metrics"})
        metrics["storage_operations_counter"].add(1, {"operation": "store_metrics", "count": metric_count})
    else:
        # Legacy format - handle array or single metric
        metrics_data = data if isinstance(data, list) else [data]

        # Filter valid metrics
        valid_metrics = [m for m in metrics_data if isinstance(m, dict) and 'name' in m]

        if valid_metrics:
            await storage.store_metrics(valid_metrics)

            # Track ingestion metrics
            metrics["ingestion_counter"].add(len(valid_metrics), {"type": "metrics"})
            metrics["storage_operations_counter"].add(1, {"operation": "store_metrics", "count": len(valid_metrics)})

    return {'status': 'ok'}
