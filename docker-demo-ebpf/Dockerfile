FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY prom_remote_write_v2.py .
COPY remote_write_pb2.py .

ENV PYTHONUNBUFFERED=1
ENV OTEL_SERVICE_NAME=ebpf-frontend
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
ENV OTEL_METRIC_EXPORT_INTERVAL=5000

EXPOSE 5000

# No opentelemetry-instrument wrapper - traces come from eBPF agent
# Metrics and logs are set up manually in app.py
CMD ["python", "-u", "app.py"]
