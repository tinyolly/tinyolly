"""HTTP middleware configuration"""

import time

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..config import settings
from .telemetry import get_metrics


def endpoint_label(request: Request) -> str:
    """Low-cardinality endpoint label: the matched route template ("/api/traces/{trace_id}"), never the raw
    path, so scanners or per-id URLs cannot create unbounded metric series."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    if request.url.path.startswith("/static/"):
        return "/static/*"
    return "unmatched"


def setup_middleware(app):
    """Setup all middleware for the FastAPI app"""
    metrics = get_metrics()
    
    # Add custom metrics middleware
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        """Track request metrics for all HTTP endpoints"""
        start_time = time.time()

        try:
            response = await call_next(request)
            endpoint = endpoint_label(request)   # resolved after routing so the template is available

            metrics["request_counter"].add(1, {"method": request.method, "endpoint": endpoint})
            
            # Track response time
            duration_ms = (time.time() - start_time) * 1000
            metrics["response_time_histogram"].record(duration_ms, {
                "method": request.method,
                "endpoint": endpoint,
                "status": response.status_code
            })
            
            # Track errors
            if response.status_code >= 400:
                metrics["error_counter"].add(1, {
                    "method": request.method,
                    "endpoint": endpoint,
                    "status": response.status_code
                })
            
            # Prevent browser caching of static JS/CSS so deploys pick up immediately
            if request.url.path.startswith("/static/") and request.url.path.endswith((".js", ".css")):
                response.headers["Cache-Control"] = "no-cache"
            
            return response
        except Exception as e:
            # Track exceptions
            metrics["request_counter"].add(1, {"method": request.method, "endpoint": endpoint_label(request)})
            metrics["error_counter"].add(1, {
                "method": request.method,
                "endpoint": endpoint_label(request),
                "error_type": type(e).__name__
            })
            raise
    
    # CORS: open (local-only deployment)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add GZip compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
