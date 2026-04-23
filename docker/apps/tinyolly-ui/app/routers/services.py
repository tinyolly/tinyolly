"""Service-related endpoints"""

from typing import Dict, Any, List
from fastapi import APIRouter, Query, Depends

from models import ServiceMap
from ..dependencies import get_storage
from tinyolly_common import Storage

router = APIRouter(prefix="/api", tags=["Services"])


@router.get(
    '/service-map',
    response_model=ServiceMap,
    operation_id="get_service_map",
    summary="Get service dependency graph",
    responses={
        200: {"description": "Service dependency graph with nodes and edges"}
    }
)
async def get_service_map(
    limit: int = Query(default=500, le=5000, description="Maximum number of traces to analyze (max 5000)"),
    storage: Storage = Depends(get_storage)
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


@router.get(
    '/service-catalog',
    response_model=List[Dict[str, Any]],
    operation_id="get_service_catalog",
    summary="Get service catalog with RED metrics",
    responses={
        200: {"description": "Service catalog with Rate, Errors, Duration metrics"}
    }
)
async def get_service_catalog(storage: Storage = Depends(get_storage)):
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


@router.post(
    '/service-map/refresh',
    response_model=Dict[str, str],
    operation_id="refresh_service_map",
    summary="Clear persisted service map",
    responses={
        200: {"description": "Persisted service map cleared; new traces are required to repopulate it"}
    }
)
async def refresh_service_map(storage: Storage = Depends(get_storage)):
    await storage.reset_service_map()
    return {"status": "ok"}


@router.post(
    '/service-catalog/refresh',
    response_model=Dict[str, str],
    operation_id="refresh_service_catalog",
    summary="Clear persisted service catalog",
    responses={
        200: {"description": "Persisted service catalog cleared; new traces are required to repopulate it"}
    }
)
async def refresh_service_catalog(storage: Storage = Depends(get_storage)):
    await storage.reset_service_catalog()
    return {"status": "ok"}


@router.get(
    '/stats',
    response_model=Dict[str, Any],
    operation_id="get_stats",
    summary="Get system statistics",
    responses={
        200: {"description": "Overall telemetry data statistics"}
    }
)
async def get_stats(storage: Storage = Depends(get_storage)):
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
