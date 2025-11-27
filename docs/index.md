<div align="center">
  <img src="images/tinyollytitle.png" alt="TinyOlly" width="500"><br>  
  <b>BYOL (Bring Your Own Laptop) Observability Platform for OpenTelemetry</b>
</div>  

---

## What is TinyOlly?

TinyOlly is located here: [https://github.com/tinyolly/tinyolly](https://github.com/tinyolly/tinyolly)  
```bash
git clone https://github.com/tinyolly/tinyolly
```

A **lightweight OpenTelemetry-native observability platform** built from scratch to visualize and correlate logs, metrics, and traces. No 3rd party observability tools - just Python (FastAPI), Redis, OpenAPI, and JavaScript.

- Think of TinyOlly as a development tool to observe and perfect your app's telemetry  
- Export metrics, logs, and traces to the Otel collector on Docker or K8S and TinyOlly will visualize and correlate them  
- Includes a **REST API** with OpenAPI docs for programmatic access to all telemetry  
- TinyOlly is *not* designed to compete with production observability platforms! It is for local development only.  

**Platform Support:**  
TinyOlly was built and tested Docker Desktop and Minikube Kubernetes on Apple Silicon Mac but may work on other platforms

---

## Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center" width="33%">
        <img src="images/traces.png" width="200"><br>
        <em>Distributed Traces</em>
      </td>
      <td align="center" width="33%">
        <img src="images/spans.png" width="200"><br>
        <em>Span Waterfall</em>
      </td>
      <td align="center" width="33%">
        <img src="images/logs.png" width="200"><br>
        <em>Real-time Logs</em>
      </td>
    </tr>
    <tr>
      <td align="center" width="33%">
        <img src="images/metrics.png" width="200"><br>
        <em>Metrics</em>
      </td>
      <td align="center" width="33%">
        <img src="images/servicecatalog.png" width="200"><br>
        <em>Service Catalog</em>
      </td>
      <td align="center" width="33%">
        <img src="images/servicemap.png" width="200"><br>
        <em>Service Map</em>
      </td>
    </tr>
  </table>
</div>

---

<div align="center">
  <p>Built for the OpenTelemetry community</p>
  <p>
    <a href="https://github.com/tinyolly/tinyolly">GitHub</a> •
    <a href="https://github.com/tinyolly/tinyolly/issues">Issues</a>
  </p>
</div>

