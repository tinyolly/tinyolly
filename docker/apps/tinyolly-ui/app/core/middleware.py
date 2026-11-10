"""HTTP middleware configuration"""

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..config import settings
from .origin import cors_origin_regex, origin_allowed
from .telemetry import get_metrics

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
    
    # Reject cross-site browser writes to every non-ingest endpoint: /api/*, /admin/* ... (see core/origin.py). Ingest (/v1) is exempt:
    # browser-based OTLP exporters legitimately post cross-origin and the collector sends no Origin.
    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method in UNSAFE_METHODS and not request.url.path.startswith("/v1/"):
            if not origin_allowed(request.headers.get("origin"), request.headers.get("host"), settings.allowed_origins):
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        return await call_next(request)

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
    
    # Add CORS middleware
    # Default to localhost only for security, can be customized via environment variable
    # Example: CORS_ORIGINS="http://localhost:*,http://127.0.0.1:*,https://example.com"
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=cors_origin_regex(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add GZip compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
