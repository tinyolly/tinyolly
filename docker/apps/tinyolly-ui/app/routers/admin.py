"""Admin endpoints"""

import datetime
import time

import psutil
from fastapi import APIRouter, Depends
from models import AdminStatsResponse, AlertConfig, AlertRule

from tinyolly_common import Storage

from ..dependencies import get_alert_manager, get_storage
from ..managers.alerts import AlertManager

router = APIRouter(prefix="/admin", tags=["System"])


@router.get(
    '/stats',
    response_model=AdminStatsResponse,
    operation_id="admin_stats",
    summary="Get detailed system statistics",
    description="""
    Get comprehensive TinyOlly performance and health metrics:

    - **Telemetry counts**: Traces, spans, logs, metrics
    - **DB usage**: SQLite file size, pages, limits
    - **Metric cardinality**: Current vs max, dropped count
    - **Process uptime**: Runtime duration

    Useful for monitoring TinyOlly's resource usage and performance.
    """
)
async def admin_stats(storage: Storage = Depends(get_storage)):
    """Get detailed admin statistics including DB and performance metrics"""
    stats = await storage.get_admin_stats()

    # Add uptime calculation
    process = psutil.Process()
    uptime_seconds = time.time() - process.create_time()
    uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))
    stats['uptime'] = uptime_str

    return stats


@router.get(
    '/alerts',
    response_model=AlertConfig,
    operation_id="get_alerts",
    summary="Get alert configuration"
)
async def get_alerts(alert_manager: AlertManager = Depends(get_alert_manager)):
    """Get all configured alert rules."""
    return AlertConfig(rules=alert_manager.rules)


@router.post(
    '/alerts',
    response_model=AlertRule,
    operation_id="create_alert",
    summary="Create alert rule"
)
async def create_alert(
    rule: AlertRule,
    alert_manager: AlertManager = Depends(get_alert_manager)
):
    """Create a new alert rule.

    **Span Error Alert Example:**
    ```json
    {
        "name": "API Errors",
        "type": "span_error",
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/...",
        "service_filter": "api-service"
    }
    ```

    **Metric Threshold Alert Example:**
    ```json
    {
        "name": "High CPU",
        "type": "metric_threshold",
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/...",
        "metric_name": "system.cpu.usage",
        "threshold": 80.0,
        "comparison": "gt"
    }
    ```
    """
    alert_manager.add_rule(rule)
    return rule


@router.delete(
    '/alerts/{rule_name}',
    operation_id="delete_alert",
    summary="Delete alert rule"
)
async def delete_alert(
    rule_name: str,
    alert_manager: AlertManager = Depends(get_alert_manager)
):
    """Delete an alert rule by name."""
    alert_manager.remove_rule(rule_name)
    return {"status": "ok", "message": f"Alert rule '{rule_name}' deleted"}
