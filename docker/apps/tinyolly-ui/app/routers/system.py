"""System endpoints (health, websocket, UI)"""

import asyncio
import logging
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models import HealthResponse
from ..dependencies import get_storage, get_connection_manager
from ..config import settings
from tinyolly_common import Storage
from ..managers.websocket import ConnectionManager

router = APIRouter(tags=["System", "UI"])

logger = logging.getLogger(__name__)

# Templates will be set up in main.py
templates = None


def set_templates(templates_instance):
    """Set templates instance from main app"""
    global templates
    templates = templates_instance


@router.get(
    '/',
    response_class=HTMLResponse,
    include_in_schema=False,
    operation_id="index"
)
async def index(request: Request):
    """Serve the main web UI dashboard"""
    if templates is None:
        raise HTTPException(status_code=500, detail="Templates not initialized")
    
    deployment_env = settings.deployment_env
    return templates.TemplateResponse(request, 'tinyolly.html', {
        'deployment_env': deployment_env
    })


@router.get(
    '/health',
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
            "description": "Service is unhealthy - storage disconnected"
        }
    }
)
async def health(storage: Storage = Depends(get_storage)):
    """
    Health check endpoint for monitoring and load balancers.

    Returns HTTP 200 when healthy, HTTP 503 when unhealthy.
    Checks storage connectivity to ensure the backend can store and retrieve data.

    Use this endpoint for:
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Monitoring system uptime checks
    """
    if await storage.is_connected():
        return {'status': 'healthy', 'storage': 'connected'}
    else:
        raise HTTPException(
            status_code=503,
            detail={'status': 'unhealthy', 'storage': 'disconnected'}
        )


@router.websocket("/ws/updates")
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
    # Get dependencies directly (WebSocket doesn't support Depends)
    storage = get_storage()
    manager = get_connection_manager()
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
