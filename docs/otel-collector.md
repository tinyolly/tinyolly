# OpenTelemetry Collector

<div align="center">
  <img src="../images/logs.png" alt="OpenTelemetry Collector" width="600">
  <p><em>Logs flowing through the OpenTelemetry Collector to TinyOlly</em></p>
</div>

---

TinyOlly uses the [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) as the telemetry ingestion and shipping layer. The collector receives telemetry from your applications and forwards it to TinyOlly's OTLP receiver.

## Configuration

TinyOlly includes a sample collector configuration that you can customize for your needs. The configuration files are located at:

- **Docker**: `docker/otelcol-configs/config.yaml`
- **Kubernetes**: `k8s/otel-collector-config.yaml`

## Default Configuration

The default configuration includes:

- **OTLP Receivers**: Accepts telemetry on ports 4317 (gRPC) and 4318 (HTTP)
- **OpAMP Extension**: Enables remote configuration management via TinyOlly UI
- **Span Metrics Connector**: Automatically generates RED metrics from traces
- **Batch Processor**: Batches telemetry for efficient processing
- **OTLP Exporter**: Forwards all telemetry to TinyOlly's OTLP receiver

## Customization Examples

You can extend the collector configuration to add additional capabilities. The collector uses the `otel/opentelemetry-collector-contrib` image which includes:

- **Receivers**: OTLP, Prometheus, Jaeger, Zipkin, and many more
- **Processors**: Batch, Memory Limiter, Resource Detection, Tail Sampling, Filtering
- **Connectors**: Span Metrics, Service Graph
- **Exporters**: OTLP, Prometheus, Logging, and many more

For a complete list of available components, see the [OpenTelemetry Collector Contrib documentation](https://github.com/open-telemetry/opentelemetry-collector-contrib).

## Applying Changes

### Docker

After modifying `docker/otelcol-configs/config.yaml` rebuild/restart using:  
```bash
cd docker
./01-start-core.sh
```

### Kubernetes

After modifying `k8s/otel-collector-config.yaml`: rebuild/restart using:  
```bash
kubectl apply -f k8s/otel-collector-config.yaml
kubectl rollout restart deployment/otel-collector
```

## Using Your Own Collector

You can use your own OpenTelemetry Collector instance instead of the one bundled with TinyOlly. This is useful if you have an existing collector setup or want to test specific collector configurations.

To do this, deploy the **Core-Only** version of TinyOlly (see [Docker Deployment](docker.md#5-tinyolly-core-only-deployment-use-your-own-docker-opentelemetry-collector) or [Kubernetes Deployment](kubernetes.md#4-tinyolly-core-only-deployment-use-your-own-kubernetes-opentelemetry-collector)).

Then, configure your collector's OTLP exporter to send data to the TinyOlly Receiver:

- **Endpoint**: `tinyolly-otlp-receiver:4343` (or `localhost:4343` from host)
- **Protocol**: gRPC
- **TLS**: Insecure (or configured as needed)

Example Exporter Configuration:
```yaml
exporters:
  otlp:
    endpoint: "tinyolly-otlp-receiver:4343"
    tls:
      insecure: true
```

**OpAMP Configuration (Optional):**

To enable remote configuration management via TinyOlly UI, add the OpAMP extension to your collector config:

```yaml
extensions:
  opamp:
    server:
      ws:
        endpoint: ws://localhost:4320/v1/opamp

service:
  extensions: [opamp]
```

The default configuration template (located at `docker/otelcol-configs/config.yaml`) shows a complete example with OTLP receivers, OpAMP extension, batch processing, and spanmetrics connector. Your collector will connect to the OpAMP server and receive configuration updates through the TinyOlly UI.