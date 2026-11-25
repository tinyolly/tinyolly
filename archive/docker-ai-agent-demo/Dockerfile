FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Auto-discover and install all applicable instrumentation libraries
RUN opentelemetry-bootstrap -a install

COPY agent.py .

# Use opentelemetry-instrument to wrap the application
# All configuration via environment variables - true zero-code!
CMD ["opentelemetry-instrument", "python", "-u", "agent.py"]
