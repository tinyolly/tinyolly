"""Alert manager for handling alert rules and notifications"""

import asyncio
import ipaddress
import json
import logging
import os
import time
from typing import Dict, List, Set
from urllib.parse import urlsplit

import aiohttp
from models import AlertRule

from tinyolly_common.otlp_utils import is_error_status

logger = logging.getLogger(__name__)


WEBHOOK_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "60"))
WEBHOOK_MAX_CONCURRENCY = int(os.getenv("ALERT_MAX_CONCURRENCY", "5"))


def validate_webhook_url(url: str) -> str:
    """Return the URL if it is an http(s) URL that does not target a link-local / metadata address, else raise ValueError.

    Alert rules can be created through the unauthenticated API, so a webhook URL is attacker-influenced input.
    Loopback and private ranges stay allowed (local webhook sinks and docker/k8s service names are the normal use
    in a local dev tool); link-local (169.254.0.0/16 incl. cloud metadata, fe80::/10) and non-http schemes are not.
    """
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("webhook_url must be an http(s) URL")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        if parts.hostname.lower() in ("metadata.google.internal", "metadata"):
            raise ValueError("webhook_url must not target a metadata service") from None
        return url
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("webhook_url must not target a link-local, multicast or unspecified address")
    return url


class AlertManager:
    """Manages alert rules and webhook notifications.

    Handles alerting for span errors and metric threshold breaches.
    """

    def __init__(self):
        """Initialize alert manager with empty rules."""
        self.rules: List[AlertRule] = []
        self._last_sent: Dict[str, float] = {}      # rule name -> monotonic time of the last webhook
        self._suppressed: Dict[str, int] = {}       # rule name -> alerts skipped during the cooldown
        self._tasks: Set[asyncio.Task] = set()
        self._sem = None                            # created lazily inside the running loop
        self._load_rules_from_env()

    def _load_rules_from_env(self):
        """Load alert rules from environment variables.

        Format: ALERT_RULES='[{"name":"...", "type":"...", "webhook_url":"...", ...}]'
        """
        rules_json = os.getenv("ALERT_RULES", "[]")
        try:
            rules_data = json.loads(rules_json)
            for rule_data in rules_data:
                rule = AlertRule(**rule_data)
                validate_webhook_url(rule.webhook_url)
                self.rules.append(rule)
            if self.rules:
                logger.info(f"Loaded {len(self.rules)} alert rules from environment")
        except Exception as e:
            logger.error(f"Error loading alert rules: {e}")

    def add_rule(self, rule: AlertRule):
        """Add a new alert rule.

        Args:
            rule (AlertRule): Alert rule to add
        """
        validate_webhook_url(rule.webhook_url)   # raises ValueError; the API turns that into a 422/400
        self.rules.append(rule)
        logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str):
        """Remove an alert rule by name.

        Args:
            rule_name (str): Name of rule to remove
        """
        self.rules = [r for r in self.rules if r.name != rule_name]
        logger.info(f"Removed alert rule: {rule_name}")

    async def check_span_error(self, span: dict):
        """Check if span has error and trigger alerts.

        Args:
            span (dict): Span data to check
        """
        # Check if span has error status
        status = span.get('status', {}) or {}
        if is_error_status(status):  # accepts 2 and "STATUS_CODE_ERROR" (the old `== 2` missed the latter)
            for rule in self.rules:
                if not rule.enabled or rule.type != "span_error":
                    continue

                # Apply service filter if specified
                if rule.service_filter and span.get('serviceName') != rule.service_filter:
                    continue

                # Trigger alert
                await self._send_webhook(rule, {
                    "alert_type": "span_error",
                    "rule_name": rule.name,
                    "span_id": span.get('spanId'),
                    "trace_id": span.get('traceId'),
                    "service": span.get('serviceName'),
                    "operation": span.get('name'),
                    "error_message": status.get('message', 'Unknown error'),
                    "timestamp": span.get('startTimeUnixNano')
                })

    async def check_metric_threshold(self, metric_name: str, value: float):
        """Check if metric exceeds threshold and trigger alerts.

        Args:
            metric_name (str): Name of the metric
            value (float): Current metric value
        """
        for rule in self.rules:
            if not rule.enabled or rule.type != "metric_threshold":
                continue

            if rule.metric_name != metric_name:
                continue

            # Check threshold
            triggered = False
            if rule.comparison == "gt" and value > rule.threshold:
                triggered = True
            elif rule.comparison == "lt" and value < rule.threshold:
                triggered = True
            elif rule.comparison == "eq" and value == rule.threshold:
                triggered = True

            if triggered:
                await self._send_webhook(rule, {
                    "alert_type": "metric_threshold",
                    "rule_name": rule.name,
                    "metric_name": metric_name,
                    "current_value": value,
                    "threshold": rule.threshold,
                    "comparison": rule.comparison,
                    "timestamp": int(time.time() * 1e9)
                })

    async def _send_webhook(self, rule: AlertRule, payload: dict):
        """Queue a webhook notification without blocking the caller (ingest).

        Alerts used to be awaited serially inside the ingest request, once per error span: a slow webhook
        stalled ingestion and a burst of errors meant a burst of identical webhooks. Now: one webhook per rule
        per cooldown window (the count of skipped ones is included in the next payload), sent as a bounded
        background task.
        """
        now = time.monotonic()
        last = self._last_sent.get(rule.name)
        if last is not None and now - last < WEBHOOK_COOLDOWN_SECONDS:
            self._suppressed[rule.name] = self._suppressed.get(rule.name, 0) + 1
            return
        self._last_sent[rule.name] = now
        suppressed = self._suppressed.pop(rule.name, 0)
        if suppressed:
            payload = {**payload, "suppressed_since_last": suppressed}

        task = asyncio.get_running_loop().create_task(self._deliver(rule, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, rule: AlertRule, payload: dict):
        if self._sem is None:
            self._sem = asyncio.Semaphore(WEBHOOK_MAX_CONCURRENCY)
        async with self._sem:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        rule.webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=5),
                        allow_redirects=False,   # a redirect could point at an address validate_webhook_url refuses
                    ) as response:
                        if response.status >= 400:
                            logger.error(f"Webhook failed: {response.status} for rule {rule.name}")
                        else:
                            logger.info(f"Alert sent for rule {rule.name}")
            except Exception as e:
                logger.error(f"Error sending webhook for rule {rule.name}: {e}")
