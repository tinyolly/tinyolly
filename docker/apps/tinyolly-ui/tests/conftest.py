"""
Pytest configuration and fixtures for TinyOlly UI tests.

This file provides shared fixtures for testing the SQLite storage backend,
API endpoints, and data processing functionality.
"""
import os
import tempfile

import pytest
import pytest_asyncio

# TODO: Import storage module after SQLite migration
# from app.storage import SQLiteStorage


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest_asyncio.fixture
async def storage(temp_db_path):
    """
    Create a SQLite storage instance for testing.

    TODO: Implement after SQLite migration (Phase 1)
    """
    # storage = SQLiteStorage(temp_db_path)
    # await storage.initialize()
    # yield storage
    # await storage.close()
    pytest.skip("SQLite storage not yet implemented")


@pytest.fixture
def sample_trace():
    """Sample trace data for testing."""
    return {
        "trace_id": "abc123def456",
        "root_span_name": "HTTP GET /api/users",
        "root_service_name": "api-gateway",
        "span_count": 5,
        "start_time_unix_nano": 1704067200000000000,
        "end_time_unix_nano": 1704067200100000000,
        "duration_ns": 100000000,
        "status": "OK"
    }


@pytest.fixture
def sample_span():
    """Sample span data for testing."""
    return {
        "trace_id": "abc123def456",
        "span_id": "span001",
        "parent_span_id": "",
        "name": "HTTP GET /api/users",
        "kind": 2,  # SERVER
        "start_time_unix_nano": 1704067200000000000,
        "end_time_unix_nano": 1704067200100000000,
        "status_code": 1,  # OK
        "status_message": "",
        "service_name": "api-gateway",
        "attributes": {"http.method": "GET", "http.url": "/api/users"},
        "events": [],
        "links": []
    }


@pytest.fixture
def sample_log():
    """Sample log record for testing."""
    return {
        "timestamp_unix_nano": 1704067200000000000,
        "observed_timestamp_unix_nano": 1704067200001000000,
        "severity_number": 9,  # INFO
        "severity_text": "INFO",
        "body": "User login successful",
        "trace_id": "abc123def456",
        "span_id": "span001",
        "service_name": "auth-service",
        "attributes": {"user.id": "user123", "event.type": "login"}
    }


@pytest.fixture
def sample_metric_gauge():
    """Sample gauge metric for testing."""
    return {
        "name": "system.cpu.usage",
        "description": "CPU usage percentage",
        "unit": "%",
        "type": "gauge",
        "service_name": "host-agent",
        "data_points": [
            {
                "timestamp_unix_nano": 1704067200000000000,
                "value": 45.5,
                "attributes": {"host": "server-01", "cpu": "0"}
            }
        ]
    }


@pytest.fixture
def sample_metric_sum():
    """Sample sum/counter metric for testing."""
    return {
        "name": "http.requests.total",
        "description": "Total HTTP requests",
        "unit": "1",
        "type": "sum",
        "is_monotonic": True,
        "aggregation_temporality": 2,  # CUMULATIVE
        "service_name": "api-gateway",
        "data_points": [
            {
                "timestamp_unix_nano": 1704067200000000000,
                "value": 1000,
                "attributes": {"method": "GET", "status": "200"}
            }
        ]
    }


@pytest.fixture
def sample_metric_histogram():
    """Sample histogram metric for testing."""
    return {
        "name": "http.request.duration",
        "description": "HTTP request duration",
        "unit": "ms",
        "type": "histogram",
        "aggregation_temporality": 2,  # CUMULATIVE
        "service_name": "api-gateway",
        "data_points": [
            {
                "timestamp_unix_nano": 1704067200000000000,
                "count": 100,
                "sum": 5000.0,
                "bucket_counts": [10, 30, 40, 15, 5],
                "explicit_bounds": [10, 50, 100, 500],
                "min": 5.0,
                "max": 750.0,
                "attributes": {"method": "GET", "path": "/api/users"}
            }
        ]
    }


@pytest.fixture
def sample_metric_summary():
    """Sample summary metric for testing."""
    return {
        "name": "http.request.latency",
        "description": "HTTP request latency summary",
        "unit": "ms",
        "type": "summary",
        "service_name": "api-gateway",
        "data_points": [
            {
                "timestamp_unix_nano": 1704067200000000000,
                "count": 100,
                "sum": 5000.0,
                "quantile_values": [
                    {"quantile": 0.5, "value": 45.0},
                    {"quantile": 0.9, "value": 95.0},
                    {"quantile": 0.99, "value": 150.0}
                ],
                "attributes": {"method": "GET"}
            }
        ]
    }


@pytest.fixture
def sample_service():
    """Sample service catalog entry for testing."""
    return {
        "name": "api-gateway",
        "attributes": {
            "service.version": "1.0.0",
            "deployment.environment": "production"
        },
        "first_seen": 1704067200000000000,
        "last_seen": 1704067300000000000
    }
