"""
TinyOlly OTLP Receiver - gRPC Implementation with Async Storage
Receives OTLP data from OpenTelemetry Collector via gRPC and stores in Redis
Optimized with Batch Operations and uvloop
"""
import grpc
from concurrent import futures
import time
import sys
import asyncio
import threading
import uvloop
import os
import logging

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

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2_grpc
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2_grpc
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2

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

def run_async(coro):
    """Run a coroutine in the shared event loop"""
    loop = get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

class TraceService(trace_service_pb2_grpc.TraceServiceServicer):
    """gRPC service for receiving traces"""
    
    def Export(self, request, context):
        """Handle trace export requests"""
        try:
            # Run async storage operations in shared event loop
            run_async(self._process_traces(request))
            return trace_service_pb2.ExportTraceServiceResponse()
            
        except Exception as e:
            logger.error(f"Error processing traces: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return trace_service_pb2.ExportTraceServiceResponse()
    
    async def _process_traces(self, request):
        """Process traces asynchronously - convert protobuf to OTLP JSON"""
        from google.protobuf.json_format import MessageToDict
        
        otlp_data = MessageToDict(
            request,
            preserving_proto_field_name=False,  # Use camelCase for consistency
            always_print_fields_with_no_presence=False,
            use_integers_for_enums=False
        )
        
        # Store in OTLP format
        await storage.store_traces(otlp_data)


class LogsService(logs_service_pb2_grpc.LogsServiceServicer):
    """gRPC service for receiving logs"""
    
    def Export(self, request, context):
        """Handle log export requests"""
        try:
            run_async(self._process_logs(request))
            return logs_service_pb2.ExportLogsServiceResponse()
            
        except Exception as e:
            logger.error(f"Error processing logs: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return logs_service_pb2.ExportLogsServiceResponse()
    
    async def _process_logs(self, request):
        """Process logs asynchronously - convert protobuf to OTLP JSON"""
        from google.protobuf.json_format import MessageToDict
        
        otlp_data = MessageToDict(
            request,
            preserving_proto_field_name=False,  # Use camelCase for consistency
            always_print_fields_with_no_presence=False,
            use_integers_for_enums=False
        )
        
        # Store in OTLP format
        await storage.store_logs_otlp(otlp_data)


class MetricsService(metrics_service_pb2_grpc.MetricsServiceServicer):
    """gRPC service for receiving metrics"""
    
    def Export(self, request, context):
        """Handle metric export requests"""
        try:
            run_async(self._process_metrics(request))
            return metrics_service_pb2.ExportMetricsServiceResponse()
            
        except Exception as e:
            logger.error(f"Error processing metrics: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return metrics_service_pb2.ExportMetricsServiceResponse()
    
    async def _process_metrics(self, request):
        """Process metrics asynchronously - convert protobuf to OTLP JSON"""
        # Convert protobuf to OTLP JSON format for storage
        from google.protobuf.json_format import MessageToDict
        
        otlp_data = MessageToDict(
            request,
            preserving_proto_field_name=False,  # Use camelCase for consistency with existing code
            always_print_fields_with_no_presence=False,
            use_integers_for_enums=False
        )
        
        # Store in OTLP format
        await storage.store_metrics(otlp_data)


def serve(port=4343):
    """Start the gRPC server"""
    # Initialize the event loop before starting the server
    get_event_loop()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Register services
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceService(), server)
    logs_service_pb2_grpc.add_LogsServiceServicer_to_server(LogsService(), server)
    metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(MetricsService(), server)
    
    # Listen on configured port
    # Use 0.0.0.0 to accept both IPv4 and IPv6 connections
    server.add_insecure_port(f'0.0.0.0:{port}')
    
    logger.info(f"TinyOlly OTLP Receiver (gRPC) starting on port {port}...")
    
    # Check Redis connection asynchronously
    redis_connected = run_async(storage.is_connected())
    logger.info(f"Redis connection: {redis_connected}")
    
    server.start()
    logger.info("✓ Server started successfully")
    
    try:
        while True:
            time.sleep(86400)  # Keep server running
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        server.stop(0)


if __name__ == '__main__':
    # Allow port to be configured via environment variable, default to 4343
    port = int(os.environ.get('PORT', 4343))
    serve(port)
