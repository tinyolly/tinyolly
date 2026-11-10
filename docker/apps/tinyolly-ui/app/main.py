"""Main FastAPI application factory"""

import asyncio
import time
from contextlib import asynccontextmanager

import uvloop
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core.logging import setup_logging
from .core.middleware import setup_middleware
from .core.telemetry import setup_telemetry
from .dependencies import get_storage
from .routers import admin, ingest, opamp, query, services, system
from .routers.system import set_templates

# Install uvloop policy for faster event loop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Setup logging
setup_logging()

# Setup telemetry
setup_telemetry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_storage().close()     # stop the storage cleanup task on shutdown


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        lifespan=lifespan,
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
            },
            {
                "name": "OpAMP",
                "description": "OpenTelemetry Agent Management Protocol - manage collector configuration"
            }
        ]
    )

    # Setup middleware
    setup_middleware(app)

    # Mount static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # Setup templates
    templates = Jinja2Templates(directory="templates")
    templates.env.globals['cache_bust'] = str(int(time.time()))
    set_templates(templates)

    # Register routers
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(services.router)
    app.include_router(admin.router)
    app.include_router(system.router)
    app.include_router(opamp.router)

    return app


# Create app instance
app = create_app()
