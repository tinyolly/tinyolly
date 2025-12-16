"""OpenTelemetry metrics and logging setup"""

import os
import logging
import sys
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from ..config import settings


def setup_telemetry():
    """Configure OpenTelemetry metrics and logging"""
    # Create resource with service name
    resource = Resource.create({"service.name": settings.otel_service_name})

    # Set up OTLP metric exporter
    metric_exporter = OTLPMetricExporter(
        endpoint=settings.otel_exporter_otlp_metrics_endpoint
    )

    # Configure metric reader with 60s export interval
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
    meter_provider = MeterProvider(metric_readers=[metric_reader], resource=resource)
    metrics.set_meter_provider(meter_provider)

    # Set up OTLP log exporter
    log_exporter = OTLPLogExporter(
        endpoint=settings.otel_exporter_otlp_logs_endpoint
    )

    # Configure logger provider with batch processor
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    # Add OTLP handler to root logger - this sends logs to OTLP
    otlp_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(otlp_handler)

    # Also add handler to uvicorn loggers to capture HTTP requests
    for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error']:
        uv_logger = logging.getLogger(logger_name)
        uv_logger.addHandler(otlp_handler)

    # Initialize LoggingInstrumentor AFTER logger provider is set up
    # This injects trace_id and span_id into log records
    LoggingInstrumentor().instrument(set_logging_format=False)
    
    # Create meter for tinyolly-ui
    meter = metrics.get_meter("tinyolly-ui")
    
    # Create metrics
    request_counter = meter.create_counter(
        name="http.server.requests",
        description="Total HTTP requests",
        unit="1"
    )
    
    error_counter = meter.create_counter(
        name="http.server.errors",
        description="Total HTTP errors",
        unit="1"
    )
    
    response_time_histogram = meter.create_histogram(
        name="http.server.duration",
        description="HTTP request duration",
        unit="ms"
    )
    
    ingestion_counter = meter.create_counter(
        name="tinyolly.ingestion.count",
        description="Total telemetry ingestion operations",
        unit="1"
    )
    
    storage_operations_counter = meter.create_counter(
        name="tinyolly.storage.operations",
        description="Storage operations by type",
        unit="1"
    )
    
    return {
        "request_counter": request_counter,
        "error_counter": error_counter,
        "response_time_histogram": response_time_histogram,
        "ingestion_counter": ingestion_counter,
        "storage_operations_counter": storage_operations_counter,
    }


# Global metrics (initialized by setup_telemetry)
_metrics = None


def get_metrics():
    """Get the metrics dictionary"""
    global _metrics
    if _metrics is None:
        _metrics = setup_telemetry()
    return _metrics
