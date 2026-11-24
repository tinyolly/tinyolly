"""Backends: the only code that knows a telemetry product. Add one by subclassing sre.backend.Backend
and registering it in BACKENDS (select with SRE_BACKEND)."""
from .tinyolly import TinyOllyBackend

BACKENDS = {"tinyolly": TinyOllyBackend}
