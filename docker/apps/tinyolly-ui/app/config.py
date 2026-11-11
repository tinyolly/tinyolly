"""Application configuration and settings"""

import os


class Settings:
    """Application settings loaded from environment variables"""
    
    # Storage
    storage_backend: str = os.getenv("STORAGE_BACKEND", "sqlite")
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", "/data/tinyolly.db")
    sqlite_ttl_seconds: int = int(os.getenv("SQLITE_TTL_SECONDS", os.getenv("REDIS_TTL", "1800")))
    max_db_size_mb: int = int(os.getenv("MAX_DB_SIZE_MB", "256"))
    
    # Server
    port: int = int(os.getenv("PORT", "5002"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    # OpAMP
    opamp_server_url: str = os.getenv("OPAMP_SERVER_URL", "http://localhost:4321")
    otelcol_default_config: str = os.getenv("OTELCOL_DEFAULT_CONFIG", "/app/otelcol-config.yaml")
    otelcol_templates_dir: str = os.getenv("OTELCOL_TEMPLATES_DIR", "/app/otelcol-templates")
    otel_collector_container: str = os.getenv("OTEL_COLLECTOR_CONTAINER", "otel-collector")
    
    # OTLP
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "tinyolly-ui")
    otel_exporter_otlp_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:4318"
    )
    otel_exporter_otlp_metrics_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "http://localhost:4318/v1/metrics"
    )
    otel_exporter_otlp_logs_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "http://localhost:4318/v1/logs"
    )
    
    # Deployment
    deployment_env: str = os.getenv("DEPLOYMENT_ENV", "docker")


settings = Settings()
