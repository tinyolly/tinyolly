import asyncio
import concurrent.futures
import importlib.util
import os
import pathlib
import tempfile

import grpc
import pytest

os.environ["SQLITE_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")   # module creates Storage() on import
_path = pathlib.Path(__file__).resolve().parents[1] / "tinyolly-otlp-receiver.py"
_spec = importlib.util.spec_from_file_location("tinyolly_otlp_receiver", _path)
rx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx)


class Ctx:
    code = details = None

    def set_code(self, c):
        self.code = c

    def set_details(self, d):
        self.details = d


def test_run_async_times_out_and_cancels():
    async def hang():
        await asyncio.sleep(30)

    with pytest.raises(concurrent.futures.TimeoutError):
        rx.run_async(hang(), timeout=0.2)


def test_timeout_maps_to_deadline_exceeded(monkeypatch):
    async def hang(_):
        await asyncio.sleep(30)

    monkeypatch.setattr(rx.storage, "store_logs_otlp", hang)
    monkeypatch.setattr(rx, "RPC_TIMEOUT_SECONDS", 0.2)
    ctx = Ctx()
    rx.LogsService().Export(rx.logs_service_pb2.ExportLogsServiceRequest(), ctx)
    assert ctx.code == grpc.StatusCode.DEADLINE_EXCEEDED


def test_conversion_happens_in_caller_thread_not_event_loop(monkeypatch):
    import threading
    seen = {}
    orig = rx.to_otlp_dict

    def spy(req):
        seen["thread"] = threading.current_thread()
        return orig(req)

    async def ok(data):
        seen["loop_thread"] = threading.current_thread()

    monkeypatch.setattr(rx, "to_otlp_dict", spy)
    monkeypatch.setattr(rx.storage, "store_metrics", ok)
    rx.MetricsService().Export(rx.metrics_service_pb2.ExportMetricsServiceRequest(), Ctx())
    assert seen["thread"] is threading.current_thread() and seen["loop_thread"] is not seen["thread"]
