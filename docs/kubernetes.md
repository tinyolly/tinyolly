# Kubernetes Deployment

All examples are launched from the repo - clone it first:  
```bash
git clone https://github.com/tinyolly/tinyolly
```  

## Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/docs/start/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

## 1. Deploy TinyOlly Core

1.  **Start Minikube:**

    ```bash
    minikube start
    ```

2.  **Build Images:**

    Run the build script to build the Docker images inside Minikube's Docker daemon:

    ```bash
    ./k8s/01-build-images.sh
    ```

3.  **Apply Manifests:**

    Apply the Kubernetes manifests to deploy the services:

    ```bash
    kubectl apply -f k8s/
    ```

4.  **Access the UI:**

    To access the TinyOlly UI (Service Type: LoadBalancer) on macOS with Minikube, you need to use `minikube tunnel`.

    Open a **new terminal window** and run:

    ```bash
    minikube tunnel
    ```

    You may be asked for your password. Keep this terminal open.

    Now you can access the TinyOlly UI at: [http://localhost:5002](http://localhost:5002)

5.  **Send Telemetry from Host Apps:**

    To send telemetry from applications running on your host machine (outside Kubernetes), use `kubectl port-forward` to expose the OTel Collector ports:

    Open a **new terminal window** and run:

    ```bash
    kubectl port-forward service/otel-collector 4317:4317 4318:4318
    ```

    Keep this terminal open. Now point your application's OpenTelemetry exporter to:  
    - **gRPC**: `http://localhost:4317`  
    - **HTTP**: `http://localhost:4318`  

    **Example environment variables:**
    ```bash
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    ```

    **For apps running inside the Kubernetes cluster:**  
    Use the Kubernetes service name:  
    - **gRPC**: `http://otel-collector:4317`  
    - **HTTP**: `http://otel-collector:4318`  

6.  **Clean Up:**

    Use the cleanup script to remove all TinyOlly resources:

    ```bash
    ./k8s/01-cleanup.sh
    ```

    Shut down Minikube:
    ```bash
    minikube stop
    ```
    
    Minikube may be more stable if you delete it:
    ```bash
    minikube delete
    ```

---

## 2. Demo Applications (Optional)

To see TinyOlly in action with instrumented microservices:

```bash
cd k8s-demo
./01-deploy.sh
```

To clean up the demo:
```bash
./02-cleanup.sh
```

The demo includes two microservices that automatically generate traffic, showcasing distributed tracing across service boundaries.

---

## 3. OpenTelemetry Demo (~20 Services - Optional)

To deploy the full [OpenTelemetry Demo](https://opentelemetry.io/docs/demo/) with ~20 microservices:

**Prerequisites:**
- TinyOlly must be deployed first (see Setup above)
- [Helm](https://helm.sh/docs/intro/install/) installed
- Sufficient cluster resources (demo is resource-intensive)

**Deploy:**
```bash
cd k8s-otel-demo
./01-deploy-otel-demo-helm.sh
```

This deploys all OpenTelemetry Demo services configured to send telemetry to TinyOlly's collector via HTTP on port 4318. Built-in observability tools (Jaeger, Grafana, Prometheus) are disabled.

**Cleanup:**
```bash
cd k8s-otel-demo
./02-cleanup-otel-demo-helm.sh
```

This removes the OpenTelemetry Demo but leaves TinyOlly running.

---

