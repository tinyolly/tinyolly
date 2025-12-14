"""
Demo Frontend Application
Uses OpenTelemetry auto-instrumentation for traces, metrics, and logs
Includes automatic traffic generation for continuous telemetry
"""
import random
import time
import logging
import json
import requests
import threading
import os
from flask import Flask, jsonify
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View, ExponentialBucketHistogramAggregation
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from prometheus_client import CollectorRegistry, Gauge, Counter, Histogram, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from prometheus_remote_writer import RemoteWriter
from io import StringIO

# Configure structured JSON logging with stdout handler
# OpenTelemetry auto-instrumentation will inject trace context into logs
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Ensure logs go to stdout
    ]
)
logger = logging.getLogger(__name__)

# Note: OpenTelemetry auto-instrumentation (via OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true)
# will automatically inject trace_id and span_id into log records

# Helper for structured logging
def log_json(level, message, **kwargs):
    """Log a structured JSON message"""
    log_data = {
        'message': message,
        **kwargs
    }
    getattr(logger, level)(json.dumps(log_data))

# Set up custom metrics exporter
# Note: Auto-instrumentation handles traces/logs, but we need to set up metrics manually
print("Setting up metrics exporter...", flush=True)
metric_exporter = OTLPMetricExporter(
    endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://otel-collector:4317'),
    insecure=True
)
metric_reader = PeriodicExportingMetricReader(
    metric_exporter, 
    export_interval_millis=int(os.getenv('OTEL_METRIC_EXPORT_INTERVAL', '5000'))
)

# Configure Views to use ExponentialHistogramAggregation for specific metrics
views = [
    View(
        instrument_name="demo.histogram.exponential",
        aggregation=ExponentialBucketHistogramAggregation(max_scale=20, max_size=160)
    )
]

meter_provider = MeterProvider(metric_readers=[metric_reader], views=views)
metrics.set_meter_provider(meter_provider)

meter = metrics.get_meter(__name__)
print(f"Metrics configured with endpoint: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://otel-collector:4317')}", flush=True)

# Create custom metrics
# Counter: Tracks cumulative values (always increasing)
order_counter = meter.create_counter(
    name="frontend.orders.total",
    description="Total number of orders processed",
    unit="orders"
)

request_counter = meter.create_counter(
    name="frontend.requests.total",
    description="Total number of requests by endpoint",
    unit="requests"
)

error_counter = meter.create_counter(
    name="frontend.errors.total",
    description="Total number of errors",
    unit="errors"
)

# Histogram: Records distribution of values
response_time_histogram = meter.create_histogram(
    name="frontend.response.duration",
    description="Response time distribution",
    unit="ms"
)

order_value_histogram = meter.create_histogram(
    name="frontend.order.value",
    description="Order value distribution",
    unit="dollars"
)

# UpDownCounter: Can go up and down (for gauges)
active_requests = meter.create_up_down_counter(
    name="frontend.requests.active",
    description="Number of active requests",
    unit="requests"
)

# --- DEMO RANDOMIZED METRICS ---
# 1. Counter: Randomly increasing
demo_counter = meter.create_counter(
    name="demo.random.counter",
    description="A randomized counter for demo purposes",
    unit="1"
)

# 2. UpDownCounter: Random walk
demo_updown = meter.create_up_down_counter(
    name="demo.random.updown",
    description="A randomized up-down counter",
    unit="1"
)

# 3. Explicit Histogram: Random distribution with explicit bucket bounds
demo_histogram = meter.create_histogram(
    name="demo.histogram.explicit",
    description="Explicit histogram with fixed bucket boundaries",
    unit="1"
)

# 3b. Exponential Histogram: Uses exponential bucketing (configured via View)
demo_exponential_histogram = meter.create_histogram(
    name="demo.histogram.exponential",
    description="Exponential histogram with dynamically scaled buckets",
    unit="1"
)

# 4. Observable Gauge: Random value
def get_random_gauge(options):
    return [metrics.Observation(random.uniform(0, 100))]

demo_gauge = meter.create_observable_gauge(
    name="demo.random.gauge",
    description="A randomized gauge",
    unit="1",
    callbacks=[get_random_gauge]
)

# 5. Observable UpDownCounter: Random sine waveish
def get_random_updown_gauge(options):
    import math
    val = 50 + 40 * math.sin(time.time() / 10)
    return [metrics.Observation(val)]

demo_observable_updown = meter.create_observable_up_down_counter(
    name="demo.random.observable_updown",
    description="A randomized observable up-down counter",
    unit="1",
    callbacks=[get_random_updown_gauge]
)

# Observable Gauge: Reports current value at collection time
def get_queue_size(options):
    """Simulated queue size"""
    return [metrics.Observation(random.randint(0, 50))]

queue_gauge = meter.create_observable_gauge(
    name="frontend.queue.size",
    description="Current queue size",
    unit="items",
    callbacks=[get_queue_size]
)

def get_memory_usage(options):
    """Simulated memory usage percentage"""
    return [metrics.Observation(random.uniform(45.0, 85.0))]

memory_gauge = meter.create_observable_gauge(
    name="frontend.memory.usage",
    description="Memory usage percentage",
    unit="percent",
    callbacks=[get_memory_usage]
)

# --- PROMETHEUS REMOTE WRITE METRICS ---
# Set up Prometheus metrics registry for remote write
print("Setting up Prometheus remote write metrics...", flush=True)
prom_registry = CollectorRegistry()

# Create Prometheus metrics for remote write
prom_remote_gauge = Gauge(
    'prom_remote_gauge',
    'A gauge metric sent via Prometheus remote write',
    registry=prom_registry
)

prom_remote_counter = Counter(
    'prom_remote_counter',
    'A counter metric sent via Prometheus remote write',
    registry=prom_registry
)

prom_remote_histogram = Histogram(
    'prom_remote_histogram',
    'A histogram metric sent via Prometheus remote write',
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0],
    registry=prom_registry
)

# Set up Prometheus remote write client
prom_remote_write_endpoint = os.getenv('PROM_REMOTE_WRITE_ENDPOINT', 'http://otel-collector:8888/api/v1/write')
prom_remote_write_client = RemoteWriter(
    url=prom_remote_write_endpoint,
    headers={}
)

print(f"Prometheus remote write configured with endpoint: {prom_remote_write_endpoint}", flush=True)

def send_prometheus_remote_write():
    """Background thread that updates Prometheus metrics and sends them via remote write"""
    logger.info(f"Prometheus remote write thread started (endpoint: {prom_remote_write_endpoint})")
    
    # Wait a bit for the app to fully start
    time.sleep(10)
    
    while True:
        try:
            # Update metrics with random values
            # Gauge: Random value between 0 and 100
            prom_remote_gauge.set(random.uniform(0, 100))
            
            # Counter: Increment by random amount
            prom_remote_counter.inc(random.randint(1, 5))
            
            # Histogram: Record random duration
            prom_remote_histogram.observe(random.expovariate(1.0/10))  # Exponential distribution
            
            # Collect metrics from registry and convert to remote write format
            # Generate Prometheus text format
            output = generate_latest(prom_registry)
            
            # Parse the text format and convert to remote write format
            data = []
            current_time_ms = int(time.time() * 1000)
            
            for family in text_string_to_metric_families(output.decode('utf-8')):
                for sample in family.samples:
                    metric_labels = {label: value for label, value in sample.labels.items() if label != '__name__'}
                    metric_labels['__name__'] = sample.name
                    
                    # Handle different metric types
                    if sample.name.endswith('_bucket') or sample.name.endswith('_sum') or sample.name.endswith('_count'):
                        # Histogram or summary metric
                        data.append({
                            'metric': metric_labels,
                            'values': [sample.value],
                            'timestamps': [current_time_ms]
                        })
                    else:
                        # Regular metric
                        data.append({
                            'metric': metric_labels,
                            'values': [sample.value],
                            'timestamps': [current_time_ms]
                        })
            
            # Send metrics via remote write
            if data:
                prom_remote_write_client.send(data)
                logger.debug(f"Prometheus metrics sent via remote write: {len(data)} time series")
            
            # Wait before next update (default 5 seconds)
            time.sleep(int(os.getenv('PROM_REMOTE_WRITE_INTERVAL', '5')))
            
        except Exception as e:
            logger.error(f"Prometheus remote write error: {e}", exc_info=True)
            time.sleep(5)

app = Flask(__name__)
app.config['SERVER_NAME'] = 'demo-frontend:5000'

# Backend service URL
BACKEND_URL = "http://demo-backend:5000"

# Auto-traffic generation settings
AUTO_TRAFFIC_ENABLED = os.getenv('AUTO_TRAFFIC', 'true').lower() == 'true'
TRAFFIC_INTERVAL_MIN = int(os.getenv('TRAFFIC_INTERVAL_MIN', '1'))  # seconds
TRAFFIC_INTERVAL_MAX = int(os.getenv('TRAFFIC_INTERVAL_MAX', '1'))  # seconds

def generate_auto_traffic():
    """Background thread that generates automatic traffic for demo purposes"""
    logger.info(f"Auto-traffic generation started (interval: {TRAFFIC_INTERVAL_MIN}-{TRAFFIC_INTERVAL_MAX}s)")
    
    # Wait a bit for the app to fully start
    time.sleep(10)
    
    endpoints = ['/hello', '/calculate', '/process-order', '/error', '/not-found', '/redirect', '/server-error', '/rate-limit', '/unauthorized']
    weights = [20, 15, 25, 10, 10, 5, 10, 3, 2]  # More varied error scenarios
    
    while True:
        try:
            # Choose an endpoint based on weights
            endpoint = random.choices(endpoints, weights=weights, k=1)[0]
            
            logger.info(f"Auto-traffic: calling {endpoint}")
            
            # Make internal request using container hostname
            try:
                response = requests.get(f"http://demo-frontend:5000{endpoint}", timeout=10)
                logger.info(f"Auto-traffic: {endpoint} -> {response.status_code}")
            except Exception as e:
                logger.warning(f"Auto-traffic request failed: {e}")
            
            # Random delay between requests
            delay = random.uniform(TRAFFIC_INTERVAL_MIN, TRAFFIC_INTERVAL_MAX)
            
            # Update random metrics
            demo_counter.add(random.randint(1, 5), {"label": "demo-value"})
            demo_updown.add(random.choice([-1, 1]) * random.randint(1, 10), {"label": "demo-walk"})
            demo_histogram.record(random.gauss(50, 15), {"label": "demo-dist"})
            demo_exponential_histogram.record(random.expovariate(1.0/50), {"label": "demo-expo"})
            
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Auto-traffic generation error: {e}")
            time.sleep(5)

@app.route('/')
def home():
    # Record metrics
    request_counter.add(1, {"endpoint": "home", "method": "GET"})
    active_requests.add(1)
    
    start_time = time.time()
    
    logger.info("Home endpoint called")
    result = jsonify({
        "message": "TinyOlly Demo App",
        "endpoints": ["/", "/hello", "/calculate", "/process-order", "/error"],
        "auto_traffic": "enabled" if AUTO_TRAFFIC_ENABLED else "disabled"
    })
    
    # Record response time
    duration_ms = (time.time() - start_time) * 1000
    response_time_histogram.record(duration_ms, {"endpoint": "home"})
    active_requests.add(-1)
    
    return result

@app.route('/hello')
def hello():
    # Record metrics
    request_counter.add(1, {"endpoint": "hello", "method": "GET"})
    active_requests.add(1)
    
    start_time = time.time()
    
    name = random.choice(["Alice", "Bob", "Charlie", "Diana"])
    logger.info(f"Greeting user: {name}")
    
    # Simulate some work
    work_duration = random.uniform(0.1, 0.5)
    time.sleep(work_duration)
    
    logger.info(f"Completed greeting for {name}")
    
    result = jsonify({
        "message": f"Hello, {name}!",
        "timestamp": time.time()
    })
    
    # Record response time
    duration_ms = (time.time() - start_time) * 1000
    response_time_histogram.record(duration_ms, {"endpoint": "hello"})
    active_requests.add(-1)
    
    return result

@app.route('/calculate')
def calculate():
    # Record metrics
    request_counter.add(1, {"endpoint": "calculate", "method": "GET"})
    active_requests.add(1)
    
    start_time = time.time()
    
    logger.info("Starting calculation")
    
    # Simulate complex calculation
    a = random.randint(1, 100)
    b = random.randint(1, 100)
    
    logger.info(f"Calculating {a} + {b}")
    calc_duration = random.uniform(0.2, 0.8)
    time.sleep(calc_duration)
    result = a + b
    
    logger.info(f"Calculation complete: {result}")
    
    return jsonify({
        "operation": "addition",
        "a": a,
        "b": b,
        "result": result
    })

@app.route('/process-order')
def process_order():
    """
    Complex endpoint showing distributed tracing across services.
    All spans are automatically created by OpenTelemetry instrumentation!
    """
    # Record metrics
    request_counter.add(1, {"endpoint": "process_order", "method": "GET"})
    active_requests.add(1)
    
    start_time = time.time()
    
    # Generate order details
    order_id = random.randint(1000, 9999)
    customer_id = random.randint(100, 999)
    item_count = random.randint(1, 5)
    base_price = random.uniform(10.0, 100.0) * item_count
    
    log_json('info', "Processing order", 
             order_id=order_id, 
             customer_id=customer_id, 
             item_count=item_count,
             operation="order_start")
    
    # Step 1: Validate request (local work)
    log_json('info', "Validating order", order_id=order_id, step="validation")
    time.sleep(random.uniform(0.02, 0.05))
    log_json('info', "Order validation successful", order_id=order_id, step="validation")
    
    try:
        # Step 2: Check inventory via backend service
        # OpenTelemetry auto-instrumentation automatically creates distributed trace!
        log_json('info', "Checking inventory", item_count=item_count, step="inventory_check")
        inventory_response = requests.post(
            f"{BACKEND_URL}/check-inventory",
            json={"items": item_count},
            timeout=5
        )
        inventory_data = inventory_response.json()
        in_stock = inventory_data.get('available', True)
        
        if not in_stock:
            log_json('warning', "Items not available", 
                    item_count=item_count, 
                    reason="out_of_stock")
            return jsonify({
                "status": "failed",
                "order_id": order_id,
                "message": "Items out of stock"
            }), 409
        
        log_json('info', "Inventory check complete", 
                item_count=item_count, 
                status="available")
        
        # Step 3: Calculate pricing via backend service
        log_json('info', "Calculating order pricing", 
                item_count=item_count, 
                base_price=round(base_price, 2))
        pricing_response = requests.post(
            f"{BACKEND_URL}/calculate-price",
            json={"items": item_count, "base_price": base_price},
            timeout=5
        )
        pricing_data = pricing_response.json()
        total_price = pricing_data.get('total', 0)
        
        log_json('info', "Pricing calculation complete", 
                total_price=round(total_price, 2), 
                step="pricing")
        
        # Step 4: Reserve inventory (local work)
        log_json('info', "Reserving inventory", 
                item_count=item_count, 
                step="reservation")
        time.sleep(random.uniform(0.06, 0.1))
        log_json('info', "Inventory reserved", 
                item_count=item_count)
        
        # Step 5: Process payment via backend service
        log_json('info', "Processing payment", 
                amount=round(total_price, 2), 
                step="payment")
        payment_response = requests.post(
            f"{BACKEND_URL}/process-payment",
            json={"amount": total_price},
            timeout=5
        )
        
        if payment_response.status_code == 200:
            payment_data = payment_response.json()
            receipt_id = payment_data.get('receipt_id')
            
            logger.info(f"Payment successful, receipt: {receipt_id}")
            
            # Step 6: Send confirmation (local work)
            logger.info(f"Sending confirmation to customer {customer_id}")
            time.sleep(random.uniform(0.04, 0.08))
            logger.info("Confirmation sent")
            
            logger.info(f"Order {order_id} completed successfully")
            
            # Record successful order metrics
            order_counter.add(1, {"status": "success"})
            order_value_histogram.record(total_price, {"status": "success"})
            duration_ms = (time.time() - start_time) * 1000
            response_time_histogram.record(duration_ms, {"endpoint": "process_order", "status": "success"})
            active_requests.add(-1)
            
            return jsonify({
                "status": "success",
                "order_id": order_id,
                "customer_id": customer_id,
                "items": item_count,
                "total": round(total_price, 2),
                "receipt_id": receipt_id,
                "message": "Order processed successfully"
            })
        else:
            logger.error("Payment declined")
            
            # Record failed order metrics
            order_counter.add(1, {"status": "declined"})
            error_counter.add(1, {"type": "payment_declined"})
            duration_ms = (time.time() - start_time) * 1000
            response_time_histogram.record(duration_ms, {"endpoint": "process_order", "status": "failed"})
            active_requests.add(-1)
            
            return jsonify({
                "status": "failed",
                "order_id": order_id,
                "message": "Payment was declined"
            }), 402
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Backend service error: {str(e)}")
        
        # Record error metrics
        order_counter.add(1, {"status": "error"})
        error_counter.add(1, {"type": "backend_error"})
        duration_ms = (time.time() - start_time) * 1000
        response_time_histogram.record(duration_ms, {"endpoint": "process_order", "status": "error"})
        active_requests.add(-1)
        
        return jsonify({
            "status": "error",
            "order_id": order_id,
            "message": "Service temporarily unavailable"
        }), 503

@app.route('/error')
def error():
    # Record metrics
    request_counter.add(1, {"endpoint": "error", "method": "GET"})
    active_requests.add(1)
    error_counter.add(1, {"type": "intentional"})

    logger.error("Error endpoint called - simulating failure")

    # Randomly decide what kind of error
    if random.random() > 0.5:
        logger.error("Raising ValueError")
        active_requests.add(-1)
        raise ValueError("Simulated error for testing")
    else:
        logger.warning("Returning error response")
        active_requests.add(-1)
        return jsonify({"error": "Something went wrong"}), 500

@app.route('/not-found')
def not_found():
    """Simulate 404 Not Found"""
    request_counter.add(1, {"endpoint": "not_found", "method": "GET"})
    error_counter.add(1, {"type": "not_found"})
    logger.warning("Resource not found")
    return jsonify({"error": "Resource not found"}), 404

@app.route('/unauthorized')
def unauthorized():
    """Simulate 401 Unauthorized"""
    request_counter.add(1, {"endpoint": "unauthorized", "method": "GET"})
    error_counter.add(1, {"type": "unauthorized"})
    logger.warning("Unauthorized access attempt")
    return jsonify({"error": "Unauthorized - please login"}), 401

@app.route('/rate-limit')
def rate_limit():
    """Simulate 429 Too Many Requests"""
    request_counter.add(1, {"endpoint": "rate_limit", "method": "GET"})
    error_counter.add(1, {"type": "rate_limit"})
    logger.warning("Rate limit exceeded")
    return jsonify({"error": "Too many requests, please try again later"}), 429

@app.route('/redirect')
def redirect():
    """Simulate 301/302 Redirect"""
    request_counter.add(1, {"endpoint": "redirect", "method": "GET"})
    logger.info("Redirecting to home")
    from flask import redirect as flask_redirect
    return flask_redirect('/', code=302)

@app.route('/server-error')
def server_error():
    """Simulate various 5xx errors"""
    request_counter.add(1, {"endpoint": "server_error", "method": "GET"})
    error_counter.add(1, {"type": "server_error"})

    # Randomly choose different 5xx errors
    error_type = random.choice([500, 502, 503, 504])

    if error_type == 500:
        logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500
    elif error_type == 502:
        logger.error("Bad gateway")
        return jsonify({"error": "Bad gateway - upstream service failed"}), 502
    elif error_type == 503:
        logger.error("Service unavailable")
        return jsonify({"error": "Service temporarily unavailable"}), 503
    else:  # 504
        logger.error("Gateway timeout")
        return jsonify({"error": "Gateway timeout"}), 504

if __name__ == '__main__':
    print("=" * 60)
    print("Starting demo frontend application")
    print(f"AUTO_TRAFFIC_ENABLED: {AUTO_TRAFFIC_ENABLED}")
    print("=" * 60)
    logger.info("Starting demo frontend application")
    
    # Start auto-traffic generation in background thread
    if AUTO_TRAFFIC_ENABLED:
        traffic_thread = threading.Thread(target=generate_auto_traffic, daemon=True)
        traffic_thread.start()
        print("✓ Auto-traffic generation thread started")
        logger.info("Auto-traffic generation thread started")
    else:
        print("✗ Auto-traffic generation disabled")
        logger.info("Auto-traffic generation disabled")
    
    # Start Prometheus remote write thread
    prom_remote_write_thread = threading.Thread(target=send_prometheus_remote_write, daemon=True)
    prom_remote_write_thread.start()
    print("✓ Prometheus remote write thread started")
    logger.info("Prometheus remote write thread started")
    
    app.run(host='0.0.0.0', port=5000)
