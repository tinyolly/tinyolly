"""Settings read from the environment, shared by the SQLite storage modules."""

import logging
import os

import zstandard as zstd

logger = logging.getLogger("tinyolly_common.storage_sqlite")

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/tinyolly.db")
TTL_SECONDS = int(os.getenv("SQLITE_TTL_SECONDS", os.getenv("REDIS_TTL", "1800")))
MAX_METRIC_CARDINALITY = int(os.getenv("MAX_METRIC_CARDINALITY", "1000"))
COMPRESSION_THRESHOLD = int(os.getenv("COMPRESSION_THRESHOLD_BYTES", "512"))
SERVICE_GRAPH_CACHE_TTL = int(os.getenv("SERVICE_GRAPH_CACHE_TTL", "5"))
SERVICE_VIEW_CACHE_TTL = int(os.getenv("SERVICE_VIEW_CACHE_TTL", "20"))
SERVICE_SNAPSHOT_TTL_SECONDS = int(os.getenv("SERVICE_SNAPSHOT_TTL_SECONDS", "3600"))
SERVICE_RESET_TTL_SECONDS = int(os.getenv("SERVICE_RESET_TTL_SECONDS", "86400"))
MAX_DB_SIZE_MB = int(os.getenv("MAX_DB_SIZE_MB", "256"))
SQLITE_PAGE_SIZE = 4096
MAX_PAGE_COUNT = max((MAX_DB_SIZE_MB * 1024 * 1024) // SQLITE_PAGE_SIZE, 1)

zstd_compressor = zstd.ZstdCompressor(level=3)
zstd_decompressor = zstd.ZstdDecompressor()
