"""
TinyOlly Common Package
Shared utilities and storage layer used by all TinyOlly components.
"""

__version__ = "0.1.0"

from .storage_sqlite import StorageSQLite

# SQLite is the only storage backend (Redis was removed in the modernization).
Storage = StorageSQLite

__all__ = ["Storage", "StorageSQLite"]
