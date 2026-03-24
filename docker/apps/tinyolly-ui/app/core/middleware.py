"""HTTP middleware configuration"""

import time
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..config import settings
from .telemetry import get_metrics


def setup_middleware(app):
    """Setup all middleware for the FastAPI app"""
    metrics = get_metrics()
    
    # Add custom metrics middleware
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        """Track request metrics for all HTTP endpoints"""
        start_time = time.time()
        
        # Track request
        metrics["request_counter"].add(1, {
            "method": request.method,
            "endpoint": request.url.path
        })
        
        try:
            response = await call_next(request)
            
            # Track response time
            duration_ms = (time.time() - start_time) * 1000
            metrics["response_time_histogram"].record(duration_ms, {
                "method": request.method,
                "endpoint": request.url.path,
                "status": response.status_code
            })
            
            # Track errors
            if response.status_code >= 400:
                metrics["error_counter"].add(1, {
                    "method": request.method,
                    "endpoint": request.url.path,
                    "status": response.status_code
                })
            
            # Prevent browser caching of static JS/CSS so deploys pick up immediately
            if request.url.path.startswith("/static/") and request.url.path.endswith((".js", ".css")):
                response.headers["Cache-Control"] = "no-cache"
            
            return response
        except Exception as e:
            # Track exceptions
            metrics["error_counter"].add(1, {
                "method": request.method,
                "endpoint": request.url.path,
                "error_type": type(e).__name__
            })
            raise
    
    # Add CORS middleware
    # Default to localhost only for security, can be customized via environment variable
    # Example: CORS_ORIGINS="http://localhost:*,http://127.0.0.1:*,https://example.com"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add GZip compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
