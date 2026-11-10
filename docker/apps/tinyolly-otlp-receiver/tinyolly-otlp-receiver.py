"""
TinyOlly OTLP Receiver - gRPC Implementation with Async Storage
Receives OTLP data from OpenTelemetry Collector via gRPC and stores in TinyOlly storage
Optimized with Batch Operations and uvloop
"""
import asyncio
import concurrent.futures
import logging
import os
import signal
import sys
import threading
import time
from concurrent import futures

import grpc
import uvloop

# Configure OpenTelemetry logging before other imports
# This will automatically instrument logging to send logs via OTLP
os.environ.setdefault('OTEL_SERVICE_NAME', 'tinyolly-otlp-receiver')
os.environ.setdefault('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://otel-collector:4318')
os.environ.setdefault('OTEL_EXPORTER_OTLP_PROTOCOL', 'http/protobuf')
os.environ.setdefault('OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED', 'true')

# Initialize OpenTelemetry logging instrumentation
try:
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    LoggingInstrumentor().instrument()
except ImportError:
    # If OpenTelemetry is not available, continue without instrumentation
    pass

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2, metrics_service_pb2_grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc

from tinyolly_common import Storage

# Configure logging to use standard library logger (will be instrumented by OpenTelemetry)
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

storage = Storage()

# Create a dedicated event loop for async operations
_loop = None
_loop_thread = None

def get_event_loop():
    """Get or create the shared event loop running in a background thread"""
    global _loop, _loop_thread
    
    if _loop is None:
        def run_loop():
            global _loop
            # Enable uvloop for performance
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop.run_forever()
        
        _loop_thread = threading.Thread(target=run_loop, daemon=True)
        _loop_thread.start()
        
        # Wait for loop to be created
        while _loop is None:
            time.sleep(0.01)
    
    return _loop

RPC_TIMEOUT_SECONDS = float(os.environ.get("RPC_TIMEOUT_SECONDS", "30"))
MAX_WORKERS = int(os.environ.get("GRPC_MAX_WORKERS", "10"))
MAX_CONCURRENT_RPCS = int(os.environ.get("GRPC_MAX_CONCURRENT_RPCS", str(MAX_WORKERS * 4)))
MAX_MESSAGE_BYTES = int(os.environ.get("GRPC_MAX_MESSAGE_BYTES", str(16 * 1024 * 1024)))


def run_async(coro, timeout=None):
    """Run a coroutine in the shared event loop; give up (and cancel it) after `timeout` seconds."""
    loop = get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise


def to_otlp_dict(request):
    """Protobuf -> OTLP JSON dict. Runs in the gRPC worker thread, NOT on the shared event loop,
    so converting a large batch no longer stalls every other request's storage work."""
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(
        request,
        preserving_proto_field_name=False,  # camelCase, consistent with the JSON ingest path
        always_print_fields_with_no_presence=False,
        use_integers_for_enums=False,
    )


def _fail(context, what, error):
    """Log the real error server-side; return a generic status (raw exception text can leak internals)."""
    logger.error(f"Error processing {what}: {error!r}", exc_info=True)
    if isinstance(error, concurrent.futures.TimeoutError):
        context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
        context.set_details(f"timed out storing {what}")
    else:
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"failed to process {what}")

class TraceService(trace_service_pb2_grpc.TraceServiceServicer):
    """gRPC service for receiving traces"""
    
    def Export(self, request, context):
        """Handle trace export requests"""
        try:
            # Run async storage operations in shared event loop
            run_async(storage.store_traces(to_otlp_dict(request)), timeout=RPC_TIMEOUT_SECONDS)
            return trace_service_pb2.ExportTraceServiceResponse()
            
        except Exception as e:
            _fail(context, "traces", e)
            return trace_service_pb2.ExportTraceServiceResponse()
    


class LogsService(logs_service_pb2_grpc.LogsServiceServicer):
    """gRPC service for receiving logs"""
    
    def Export(self, request, context):
        """Handle log export requests"""
        try:
            run_async(storage.store_logs_otlp(to_otlp_dict(request)), timeout=RPC_TIMEOUT_SECONDS)
            return logs_service_pb2.ExportLogsServiceResponse()
            
        except Exception as e:
            _fail(context, "logs", e)
            return logs_service_pb2.ExportLogsServiceResponse()
    


class MetricsService(metrics_service_pb2_grpc.MetricsServiceServicer):
    """gRPC service for receiving metrics"""
    
    def Export(self, request, context):
        """Handle metric export requests"""
        try:
            run_async(storage.store_metrics(to_otlp_dict(request)), timeout=RPC_TIMEOUT_SECONDS)
            return metrics_service_pb2.ExportMetricsServiceResponse()
            
        except Exception as e:
            _fail(context, "metrics", e)
            return metrics_service_pb2.ExportMetricsServiceResponse()
    


def serve(port=4343):
    """Start the gRPC server"""
    # Initialize the event loop before starting the server
    get_event_loop()
    
    # Bounded: excess concurrent RPCs are rejected with RESOURCE_EXHAUSTED instead of queueing without limit,
    # and message size is capped.
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        maximum_concurrent_rpcs=MAX_CONCURRENT_RPCS,
        options=[("grpc.max_receive_message_length", MAX_MESSAGE_BYTES)],
    )
    
    # Register services
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceService(), server)
    logs_service_pb2_grpc.add_LogsServiceServicer_to_server(LogsService(), server)
    metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(MetricsService(), server)
    
    # Listen on configured port
    # Use 0.0.0.0 to accept both IPv4 and IPv6 connections
    if server.add_insecure_port(f'0.0.0.0:{port}') == 0:
        raise RuntimeError(f"could not bind gRPC port {port}")
    
    logger.info(f"TinyOlly OTLP Receiver (gRPC) starting on port {port}...")
    
    # Check storage connection asynchronously
    storage_connected = run_async(storage.is_connected())
    logger.info(f"Storage connection: {storage_connected}")
    
    server.start()
    logger.info("✓ Server started successfully")
    
    # `docker stop` / k8s send SIGTERM: treat it like Ctrl-C so shutdown is graceful.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        while True:
            time.sleep(86400)  # Keep server running
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        server.stop(grace=5).wait()
        run_async(storage.close(), timeout=5)


if __name__ == '__main__':
    # Allow port to be configured via environment variable, default to 4343
    port = int(os.environ.get('PORT', 4343))
    serve(port)
