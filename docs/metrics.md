# Metrics & Cardinality explorer

TinyOlly provides a powerful interface for analyzing OpenTelemetry metrics, with specific tools designed to help you understand the shape and cardinality of your telemetry data.

## Metrics Table

The metrics table offers a dense, high-information view of all ingested metrics.

![Metrics Table](images/metrics.png)

Click the **Chart** button to visualize metric data over time:

![Metrics Chart](images/metrics2.png)

### Key Columns

- **Name**: The full OTel metric name (e.g., `http.server.response.size`).
- **Unit**: The unit of measurement (e.g., `By`, `ms`).
- **Type**: The metric type (Histogram, Sum, Gauge, etc.).
- **Resources**: Click to view the unique resource combinations associated with this metric.
- **Cardinality**: Shows the number of label dimensions vs the total number of unique time series (e.g., `8 labels / 185 series`).

---

## Cardinality Explorer

Clicking on the blue **Cardinality** link for any metric opens the **Cardinality Explorer**. This tool is essential for understanding "high cardinality" issues and exploring your data's dimensions.

### 1. Header Stats
- **Total Series (Historic)**: The total number of unique time series seen for this metric since startup (persisted in Redis).
- **Active Series (1h)**: The count of series seen in the last hour.
- **Label Dimensions**: The number of unique label keys (e.g., `http.method`, `http.status_code`).

### 2. Label Analysis Table
This table helps you identify which labels are contributing most to your cardinality.

- **Label Name**: The key of the label.
- **Cardinality**: The number of unique values for this label.
- **Values (Top 5)**: A preview of the most common values.
    - If there are more than 5 values, a clickable **`...`** link expands the list to show all values inline.

### 3. Raw Active Series
A scrollable view of all active series in a PromQL-like syntax:

```promql
{container.id="...", http.method="GET", http.route="/api/traces", http.status_code="200", service.name="tinyolly-ui"}
{container.id="...", http.method="GET", http.route="/health", http.status_code="200", service.name="tinyolly-ui"}
```

### Export Actions
Use the buttons in the "Raw Active Series" section to export data for offline analysis:

- **Copy PromQL**: Copies the visible series list to your clipboard.
- **Download JSON**: Downloads the full series object as a JSON file.

---

## Cardinality Protection

TinyOlly includes built-in protection against cardinality explosions to prevent memory exhaustion during local development.

- **Hard Limit**: 1000 unique metric names (configurable).
- **Visual Warnings**: 
    - ⚠️ **Yellow**: > 70% capacity
    - 🔴 **Red**: > 90% capacity
- **Behavior**: Metrics exceeding the limit are dropped, and a system alert is triggered.

See [Cardinality Protection](CARDINALITY-PROTECTION.md) for more details.
