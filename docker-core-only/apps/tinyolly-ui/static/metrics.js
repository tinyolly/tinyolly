/**
 * Metrics Module - OTEL Format with Resources, Attributes, and Exemplars
 */
import { loadChartJs, renderActionButton, copyToClipboard, downloadJson, renderEmptyState, getColorForIndex, createModal, closeModal } from './utils.js';

// State management
let allMetrics = [];
let activeResourceFilters = {}; // {key: value}
let expandedMetric = null;
let allResourceKeys = new Set(); // All unique resource keys across metrics
let showOnlyRED = false;

// Type badge colors
const TYPE_BADGES = {
    gauge: { color: '#10b981', label: 'Gauge' },
    sum: { color: '#3b82f6', label: 'Sum' },
    histogram: { color: '#f97316', label: 'Histogram' },
    summary: { color: '#a855f7', label: 'Summary' }
};

export async function renderMetrics(metricsData) {
    const container = document.getElementById('metrics-container');

    if (!metricsData || metricsData.length === 0) {
        container.innerHTML = renderEmptyState('📊', 'No metrics collected yet');
        return;
    }

    // Store metrics globally
    allMetrics = metricsData;

    // Extract all unique resource keys
    extractResourceKeys();

    // Render resource filters section
    renderResourceFilters();

    // Filter metrics based on active resource filters and RED filter
    let filteredMetrics = filterMetricsByResources(allMetrics);

    // Apply RED filter if enabled
    if (showOnlyRED) {
        filteredMetrics = filteredMetrics.filter(m =>
            m.name.startsWith('traces.span.metrics.')
        );
    }

    // Update filter button appearance
    const filterBtn = document.getElementById('metric-filter-toggle');
    if (filterBtn) {
        filterBtn.textContent = showOnlyRED ? 'Show All Metrics' : 'Show RED Metrics Only';
        filterBtn.style.background = showOnlyRED ? '#6b7280' : 'var(--primary)';
    }

    // Add metric count header
    const METRIC_LIMIT = 1000;
    const metricCount = allMetrics.length;
    const percentUsed = Math.round((metricCount / METRIC_LIMIT) * 100);
    const isNearLimit = percentUsed >= 80;

    const countHeader = document.createElement('div');
    countHeader.style.cssText = `
        display: flex; 
        justify-content: space-between; 
        align-items: center; 
        padding: 12px 16px; 
        background: var(--bg-card); 
        border: 1px solid var(--border-color); 
        border-radius: 8px; 
        margin-bottom: 15px;
        box-shadow: var(--shadow);
    `;

    countHeader.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 14px; font-weight: 600; color: var(--text-main);">Metrics Overview</span>
            <span style="font-size: 12px; color: var(--text-muted);">
                ${filteredMetrics.length !== metricCount ? `Showing ${filteredMetrics.length} of ${metricCount}` : `${metricCount} total`}
            </span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 13px; color: ${isNearLimit ? '#ef4444' : 'var(--text-main)'}; font-weight: 600;">
                ${metricCount}/${METRIC_LIMIT}
            </span>
            <span style="font-size: 12px; color: var(--text-muted);">limit</span>
            ${isNearLimit ? `<span style="font-size: 11px; color: #ef4444; background: #fee2e2; padding: 2px 8px; border-radius: 12px;">⚠️ ${percentUsed}%</span>` : ''}
        </div>
    `;

    // Build metrics table
    const tableContainer = document.createElement('div');
    tableContainer.style.cssText = 'background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; box-shadow: var(--shadow);';

    const headerHtml = `
        <div style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            <div style="flex: 1; min-width: 200px;">Name</div>
            <div style="flex: 0 0 80px;">Type</div>
            <div style="flex: 0 0 100px;">Resources</div>
            <div style="flex: 0 0 120px;">Attributes</div>
            <div style="flex: 0 0 60px; text-align: center;">Chart</div>
        </div>
    `;

    tableContainer.innerHTML = headerHtml;

    // Render each metric row
    for (const metric of filteredMetrics) {
        const rowDiv = createMetricRow(metric);
        tableContainer.appendChild(rowDiv);
    }

    container.innerHTML = '';
    container.appendChild(countHeader);
    container.appendChild(tableContainer);
}

function extractResourceKeys() {
    allResourceKeys.clear();
    // We'll populate this when fetching full metric data
    // For now, common keys
    allResourceKeys.add('service.name');
    allResourceKeys.add('host.name');
    allResourceKeys.add('deployment.environment');
}

function renderResourceFilters() {
    const filterContainer = document.getElementById('resource-filters-section');
    if (!filterContainer) return;

    let html = '<div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center;">';
    html += '<span style="font-weight: 600; font-size: 13px;">Resource Filters:</span>';

    // Active filter chips
    for (const [key, value] of Object.entries(activeResourceFilters)) {
        html += `
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--primary); color: white; border-radius: 16px; font-size: 12px;">
                <span>${key}: ${value}</span>
                <button onclick="window.removeResourceFilter('${key}')" style="background: none; border: none; color: white; cursor: pointer; font-size: 14px; padding: 0; line-height: 1;">×</button>
            </span>
        `;
    }

    // Add filter dropdown
    if (allResourceKeys.size > 0) {
        html += `
            <select id="resource-key-select" onchange="window.showResourceValueInput(this.value)" style="padding: 4px 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-card); font-size: 12px;">
                <option value="">+ Add filter...</option>
                ${Array.from(allResourceKeys).map(key => {
            if (!activeResourceFilters[key]) {
                return `<option value="${key}">${key}</option>`;
            }
            return '';
        }).join('')}
            </select>
        `;
    }

    // Clear all button
    if (Object.keys(activeResourceFilters).length > 0) {
        html += `
            <button onclick="window.clearAllResourceFilters()" style="padding: 4px 10px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: 4px; font-size: 12px; cursor: pointer;">
                Clear All Filters
            </button>
        `;
    }

    html += '</div>';
    filterContainer.innerHTML = html;
}

function filterMetricsByResources(metrics) {
    if (Object.keys(activeResourceFilters).length === 0) {
        return metrics;
    }

    // For now, return all metrics (filtering happens when fetching series)
    // In a full implementation, we'd fetch resources for each metric and filter here
    return metrics;
}

function createMetricRow(metric) {
    const rowDiv = document.createElement('div');
    rowDiv.className = 'metric-row';
    rowDiv.dataset.metricName = metric.name;

    const type = metric.type ? metric.type.toLowerCase() : 'unknown';
    const typeBadge = TYPE_BADGES[type] || TYPE_BADGES.gauge;

    rowDiv.innerHTML = `
        <div class="metric-header" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 11px; cursor: pointer; transition: background 0.2s;" onmouseover="this.style.background='var(--bg-hover)'" onmouseout="this.style.background=''">
            <div style="flex: 1; min-width: 200px;">
                <div style="font-weight: 500; color: var(--text-main); font-size: 13px;">${metric.name}</div>
                ${metric.description ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">${metric.description}</div>` : ''}
                ${metric.unit ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">Unit: ${metric.unit}</div>` : ''}
            </div>
            <div style="flex: 0 0 80px;">
                <span style="padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: 600; background: ${typeBadge.color}20; color: ${typeBadge.color};">
                    ${typeBadge.label}
                </span>
            </div>
            <div class="metric-resources-link" data-metric-name="${metric.name}" style="flex: 0 0 100px; font-size: 11px; color: var(--primary); cursor: pointer; text-decoration: underline;" onclick="event.stopPropagation(); window.showMetricResources('${metric.name}', ${metric.resource_count});">
                ${metric.resource_count} ${metric.resource_count === 1 ? 'resource' : 'resources'}
            </div>
            <div class="metric-attributes-link" data-metric-name="${metric.name}" style="flex: 0 0 120px; font-size: 11px; color: var(--primary); cursor: pointer; text-decoration: underline;" onclick="event.stopPropagation(); window.showMetricAttributes('${metric.name}', ${metric.attribute_combinations});">
                ${metric.attribute_combinations} ${metric.attribute_combinations === 1 ? 'combination' : 'combinations'}
            </div>
            <div style="flex: 0 0 60px; text-align: center;">
                <span class="metric-expand-icon" style="display: inline-block; transition: transform 0.2s;">➤</span>
            </div>
        </div>
        <div class="metric-detail-container" style="display: none; background: var(--bg-card); border-bottom: 1px solid var(--border-color); padding: 16px;">
        </div>
    `;

    // Attach click handler
    const header = rowDiv.querySelector('.metric-header');
    const detailContainer = rowDiv.querySelector('.metric-detail-container');
    const expandIcon = rowDiv.querySelector('.metric-expand-icon');

    header.addEventListener('click', async () => {
        const isExpanded = detailContainer.style.display !== 'none';

        if (isExpanded) {
            detailContainer.style.display = 'none';
            expandIcon.style.transform = 'rotate(0deg)';
            expandedMetric = null;
        } else {
            detailContainer.style.display = 'block';
            expandIcon.style.transform = 'rotate(90deg)';
            expandedMetric = metric.name;

            // Load metric detail
            if (!detailContainer.dataset.loaded) {
                await renderMetricDetail(metric, detailContainer);
                detailContainer.dataset.loaded = 'true';
            }
        }
    });

    return rowDiv;
}

async function renderMetricDetail(metric, container) {
    try {
        container.innerHTML = '<div style="text-align: center; padding: 20px;">Loading...</div>';

        // Fetch full metric data with filters
        const params = new URLSearchParams();
        for (const [key, value] of Object.entries(activeResourceFilters)) {
            params.append(`resource.${key}`, value);
        }

        const response = await fetch(`/api/metrics/${metric.name}?${params.toString()}`);
        const data = await response.json();

        // Build action buttons
        const chartId = `chart-${metric.name.replace(/[^a-zA-Z0-9]/g, '_')}`;
        const buttonsHtml = `
            ${renderActionButton(`copy-btn-${chartId}`, 'Copy Name', 'primary')}
            ${renderActionButton(`download-btn-${chartId}`, 'Download JSON', 'primary')}
            ${renderActionButton(`close-btn-${chartId}`, 'Close', 'primary')}
            <span id="copy-feedback-${chartId}" style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
        `;

        container.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color);">
                <div style="font-size: 14px; font-weight: 600; color: var(--text-main);">${metric.name}</div>
                <div style="display: flex; gap: 8px;">${buttonsHtml}</div>
            </div>
            <div id="attribute-filters-${chartId}" style="margin-bottom: 16px;"></div>
            <div id="chart-legend-${chartId}" style="margin-bottom: 16px;"></div>
            <div id="chart-container-${chartId}" style="position: relative; height: 300px;">
                <canvas id="${chartId}"></canvas>
            </div>
        `;

        // Attach button handlers
        document.getElementById(`copy-btn-${chartId}`).onclick = () => {
            copyToClipboard(metric.name, document.getElementById(`copy-feedback-${chartId}`));
        };

        document.getElementById(`download-btn-${chartId}`).onclick = () => {
            downloadJson(data, `metric-${metric.name}.json`);
        };

        document.getElementById(`close-btn-${chartId}`).onclick = () => {
            container.parentElement.querySelector('.metric-header').click();
        };

        // Render attribute filters
        renderAttributeFilters(metric, data, `attribute-filters-${chartId}`, chartId);

        // Render chart
        await loadChartJs();

        // Adjust container height for gauge charts
        const chartContainer = document.getElementById(`chart-container-${chartId}`);
        if (metric.type.toLowerCase() === 'gauge' && chartContainer) {
            chartContainer.style.height = '120px';
        }

        const canvas = document.getElementById(chartId);
        renderMetricChart(metric, data, canvas, chartId);

    } catch (error) {
        console.error('Error loading metric detail:', error);
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Error loading metric data</div>';
    }
}

function renderAttributeFilters(metric, data, containerId, chartId) {
    const container = document.getElementById(containerId);
    if (!container || !data.series || data.series.length === 0) return;

    // Extract all unique attribute keys from series
    const attrKeys = new Set();
    data.series.forEach(s => {
        Object.keys(s.attributes || {}).forEach(k => attrKeys.add(k));
    });

    if (attrKeys.size === 0) return;

    let html = '<div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">';
    html += '<span style="font-size: 12px; font-weight: 600;">Filter by:</span>';

    for (const key of attrKeys) {
        // Get unique values for this attribute
        const values = new Set();
        data.series.forEach(s => {
            const val = s.attributes?.[key];
            if (val !== undefined) values.add(String(val));
        });

        html += `
            <select onchange="window.applyAttributeFilter('${chartId}', '${key}', this.value)" style="padding: 3px 6px; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-card); font-size: 11px;">
                <option value="">All ${key}</option>
                ${Array.from(values).map(v => `<option value="${v}">${v}</option>`).join('')}
            </select>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderMetricChart(metric, data, canvas, chartId) {
    if (!data || !data.series || data.series.length === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No data available', canvas.width / 2, 150);
        console.warn('No series data for metric:', metric.name, data);
        return;
    }

    // Check if any series has datapoints
    const hasDatapoints = data.series.some(s => s.datapoints && s.datapoints.length > 0);
    if (!hasDatapoints) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No datapoints available', canvas.width / 2, 150);
        console.warn('No datapoints in series for metric:', metric.name);
        return;
    }

    const type = metric.type.toLowerCase();

    if (type === 'gauge') {
        renderGaugeChart(metric, data, canvas, chartId);
    } else if (type === 'sum') {
        renderSumChart(metric, data, canvas, chartId);
    } else if (type === 'histogram') {
        renderHistogramChart(metric, data, canvas, chartId);
    } else if (type === 'summary') {
        renderSummaryChart(metric, data, canvas, chartId);
    } else {
        renderGaugeChart(metric, data, canvas, chartId);
    }
}

function renderGaugeChart(metric, data, canvas, chartId) {
    // Show gauge as doughnut chart with current value
    if (!data.series || data.series.length === 0) {
        console.warn('No series for gauge chart:', metric.name);
        return;
    }

    // Find first series with datapoints
    let seriesWithData = data.series.find(s => s.datapoints && s.datapoints.length > 0);
    if (!seriesWithData) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No datapoints available', canvas.width / 2, 150);
        return;
    }

    // Get the latest value from the series
    const latestDp = seriesWithData.datapoints.slice(-1)[0];
    if (!latestDp) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No datapoint available', canvas.width / 2, 150);
        return;
    }

    const currentValue = latestDp.value !== null && latestDp.value !== undefined ? latestDp.value : 0;
    const label = buildSeriesLabel(seriesWithData, data.series);

    // Determine max value (use 100 as default for percentages, or 1.5x current for others)
    let maxValue = 100;
    if (metric.unit !== 'percent' && metric.unit !== '%') {
        const allValues = seriesWithData.datapoints
            .map(dp => dp.value)
            .filter(v => v !== null && v !== undefined);
        if (allValues.length > 0) {
            const maxObserved = Math.max(...allValues);
            maxValue = Math.ceil(maxObserved * 1.5);
        } else {
            maxValue = Math.max(100, currentValue * 1.5);
        }
    }

    const remaining = Math.max(0, maxValue - currentValue);

    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: [label, 'Remaining'],
            datasets: [{
                data: [currentValue, remaining],
                backgroundColor: [
                    'rgba(59, 130, 246, 0.8)',
                    'rgba(229, 231, 235, 0.3)'
                ],
                borderColor: [
                    'rgba(59, 130, 246, 1)',
                    'rgba(229, 231, 235, 0.5)'
                ],
                borderWidth: 2,
                circumference: 180,
                rotation: 270
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            if (context.dataIndex === 0) {
                                return `${label}: ${currentValue.toFixed(2)} ${metric.unit || ''}`;
                            }
                            return null;
                        }
                    }
                }
            }
        },
        plugins: [{
            afterDraw: (chart) => {
                const ctx = chart.ctx;
                const width = chart.width;
                const height = chart.height;
                const chartArea = chart.chartArea;

                ctx.save();

                // Position text in the center-bottom area of the gauge
                const centerX = (chartArea.left + chartArea.right) / 2;
                const centerY = chartArea.bottom - 30; // Position near bottom

                // Draw value
                ctx.font = 'bold 20px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = '#1f2937';
                const text = `${currentValue.toFixed(1)}`;
                ctx.fillText(text, centerX, centerY);

                // Draw unit below
                ctx.font = '11px sans-serif';
                ctx.fillStyle = '#6b7280';
                const unit = metric.unit || '';
                ctx.fillText(unit, centerX, centerY + 16);

                ctx.restore();
            }
        }]
    });
}

function renderSumChart(metric, data, canvas, chartId) {
    // Calculate rate (delta / time_delta) and show as line chart
    // Aggregate series by http.method (or span.kind if no http.method) to simplify the view

    if (!data.series || data.series.length === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No series data available', canvas.width / 2, 150);
        return;
    }

    // Filter out series without datapoints
    const seriesWithData = data.series.filter(s => s.datapoints && s.datapoints.length > 0);
    if (seriesWithData.length === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No datapoints available', canvas.width / 2, 150);
        return;
    }

    // Group series by aggregation key
    const seriesGroups = {};

    seriesWithData.forEach(series => {
        // Determine aggregation key - prefer http.method, fall back to span.kind
        let groupKey = 'Total';
        if (series.attributes && series.attributes['http.method']) {
            groupKey = series.attributes['http.method'];
        } else if (series.attributes && series.attributes['span.kind']) {
            groupKey = series.attributes['span.kind'].replace('SPAN_KIND_', '');
        }

        if (!seriesGroups[groupKey]) {
            seriesGroups[groupKey] = [];
        }
        seriesGroups[groupKey].push(series);
    });

    const datasets = [];
    let colorIdx = 0;

    // For each group, aggregate the rates
    for (const [groupKey, groupSeries] of Object.entries(seriesGroups)) {
        // Calculate rates for each series in the group
        const allRates = [];

        groupSeries.forEach(series => {
            const rates = [];
            for (let i = 1; i < series.datapoints.length; i++) {
                const prev = series.datapoints[i - 1];
                const curr = series.datapoints[i];

                // Skip if values are null/undefined
                if (prev.value === null || prev.value === undefined ||
                    curr.value === null || curr.value === undefined) {
                    continue;
                }

                const timeDelta = curr.timestamp - prev.timestamp;
                const valueDelta = curr.value - prev.value;

                if (timeDelta > 0) {
                    const rate = valueDelta / timeDelta;
                    rates.push({
                        timestamp: curr.timestamp * 1000,
                        rate: Math.max(0, rate)
                    });
                }
            }
            if (rates.length > 0) {
                allRates.push(rates);
            }
        });

        // Merge and sum rates at each timestamp
        const aggregatedRates = new Map();

        allRates.forEach(rates => {
            rates.forEach(({ timestamp, rate }) => {
                if (!aggregatedRates.has(timestamp)) {
                    aggregatedRates.set(timestamp, 0);
                }
                aggregatedRates.set(timestamp, aggregatedRates.get(timestamp) + rate);
            });
        });

        // Convert to points array and sort by timestamp
        const points = Array.from(aggregatedRates.entries())
            .map(([timestamp, rate]) => ({ x: timestamp, y: rate }))
            .sort((a, b) => a.x - b.x);

        if (points.length > 0) {
            const color = getColorForIndex(colorIdx++);
            datasets.push({
                label: `${groupKey} (rate/sec)`,
                data: points,
                borderColor: color,
                backgroundColor: color + '20',
                borderWidth: 2,
                tension: 0.4,
                fill: true,
                pointRadius: 2
            });
        }
    }

    new Chart(canvas, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(2)}/s`
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
                    title: { display: true, text: 'Time' }
                },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Rate per Second' }
                }
            }
        }
    });
}

function renderHistogramChart(metric, data, canvas, chartId) {
    // Show histogram as percentile bars (P50, P75, P90, P95, P99) over time
    if (!data.series || data.series.length === 0) return;

    const series = data.series[0];
    let histogramDps = series.datapoints.filter(dp => dp.histogram && dp.histogram.bucketCounts);

    if (histogramDps.length === 0) {
        renderGaugeChart(metric, data, canvas, chartId); // Fallback
        return;
    }

    // Sample data if we have too many points (limit to ~30 bars for readability)
    const maxBars = 30;
    if (histogramDps.length > maxBars) {
        const step = Math.ceil(histogramDps.length / maxBars);
        histogramDps = histogramDps.filter((_, idx) => idx % step === 0);
    }

    const labels = [];
    const p50Data = [];
    const p75Data = [];
    const p90Data = [];
    const p95Data = [];
    const p99Data = [];

    let measurementNumber = 0;

    for (const dp of histogramDps) {
        const hist = dp.histogram;
        const buckets = (hist.bucketCounts || []).map((count, idx) => ({
            count: count,
            bound: hist.explicitBounds[idx]
        }));

        // Calculate total count
        const totalCount = buckets.reduce((sum, b) => sum + (b.count || 0), 0);

        if (totalCount > 0) {
            const percentiles = calculatePercentilesFromBuckets(buckets);

            measurementNumber++;
            labels.push(`#${measurementNumber}`);

            p50Data.push(percentiles.p50 || 0);
            p75Data.push(percentiles.p75 || 0);
            p90Data.push(percentiles.p90 || 0);
            p95Data.push(percentiles.p95 || 0);
            p99Data.push(percentiles.p99 || 0);
        }
    }

    if (labels.length === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No histogram data available', canvas.width / 2, 150);
        return;
    }

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'P50 (Median)',
                    data: p50Data,
                    backgroundColor: 'rgba(16, 185, 129, 0.7)',
                    borderColor: '#10b981',
                    borderWidth: 1
                },
                {
                    label: 'P75',
                    data: p75Data,
                    backgroundColor: 'rgba(0, 102, 204, 0.7)',
                    borderColor: '#0066CC',
                    borderWidth: 1
                },
                {
                    label: 'P90',
                    data: p90Data,
                    backgroundColor: 'rgba(251, 146, 60, 0.7)',
                    borderColor: '#fb923c',
                    borderWidth: 1
                },
                {
                    label: 'P95',
                    data: p95Data,
                    backgroundColor: 'rgba(239, 68, 68, 0.7)',
                    borderColor: '#ef4444',
                    borderWidth: 1
                },
                {
                    label: 'P99',
                    data: p99Data,
                    backgroundColor: 'rgba(168, 85, 247, 0.7)',
                    borderColor: '#a855f7',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: { boxWidth: 12, font: { size: 11 } }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(2)} ${metric.unit || 'ms'}`
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Measurement' },
                    ticks: {
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 20
                    }
                },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: metric.unit || 'Latency (ms)' }
                }
            },
            barPercentage: 0.9,
            categoryPercentage: 0.8
        }
    });
}

function renderSummaryChart(metric, data, canvas, chartId) {
    // Show quantile values as lines
    const datasets = [];

    data.series.forEach((series, idx) => {
        const label = buildSeriesLabel(series, data.series);

        // Get quantile values from summary
        series.datapoints.forEach((dp, dpIdx) => {
            if (dp.summary && dp.summary.quantileValues) {
                dp.summary.quantileValues.forEach((qv, qIdx) => {
                    const quantileLabel = `${label} Q${qv.quantile}`;
                    let dataset = datasets.find(d => d.label === quantileLabel);

                    if (!dataset) {
                        const color = getColorForIndex(idx * 10 + qIdx);
                        dataset = {
                            label: quantileLabel,
                            data: [],
                            borderColor: color,
                            borderWidth: 2,
                            fill: false,
                            pointRadius: 2
                        };
                        datasets.push(dataset);
                    }

                    dataset.data.push({ x: dp.timestamp * 1000, y: qv.value });
                });
            }
        });
    });

    new Chart(canvas, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 10 } } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
                    title: { display: true, text: 'Time' }
                },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: metric.unit || 'Value' }
                }
            }
        }
    });
}

function addExemplarPoints(series, datasets, baseColor) {
    if (!series.exemplars || series.exemplars.length === 0) return;

    const exemplarPoints = series.exemplars.map(ex => ({
        x: ex.timestamp * 1000,
        y: ex.value,
        traceId: ex.traceId,
        spanId: ex.spanId
    }));

    datasets.push({
        label: '⭐ Exemplars',
        data: exemplarPoints,
        pointStyle: 'star',
        pointRadius: 8,
        pointBackgroundColor: '#fbbf24',
        pointBorderColor: '#f59e0b',
        pointBorderWidth: 2,
        showLine: false,
        hoverRadius: 10
    });
}

function handleExemplarClick(event, elements, seriesData) {
    if (elements.length > 0) {
        const element = elements[0];
        const dataset = element.chart.data.datasets[element.datasetIndex];

        if (dataset.label.includes('Exemplar')) {
            const point = dataset.data[element.index];
            showExemplarModal(point);
        }
    }
}

function showExemplarModal(exemplar) {
    const contentHtml = `
        <div style="display: flex; flex-direction: column; gap: 10px; font-size: 13px;">
            <div><strong>Trace ID:</strong> <code style="background: var(--bg-hover); padding: 2px 6px; border-radius: 3px;">${exemplar.traceId}</code></div>
            <div><strong>Span ID:</strong> <code style="background: var(--bg-hover); padding: 2px 6px; border-radius: 3px;">${exemplar.spanId}</code></div>
            <div><strong>Timestamp:</strong> ${new Date(exemplar.x).toLocaleString()}</div>
            <div><strong>Value:</strong> ${exemplar.y.toFixed(2)}</div>
        </div>
    `;

    const buttons = [
        {
            id: 'view-trace-btn',
            label: 'Trace',
            style: 'primary',
            handler: (modal) => {
                closeModal(modal);
                viewTraceFromExemplar(exemplar.traceId);
            }
        },
        {
            id: 'copy-trace-btn',
            label: 'Copy Trace ID',
            style: 'secondary',
            handler: () => {
                copyToClipboard(exemplar.traceId);
            }
        },
        {
            id: 'close-modal-btn',
            label: 'Close',
            style: 'secondary',
            handler: (modal) => closeModal(modal)
        }
    ];

    createModal('Exemplar Details', contentHtml, buttons);
}

function viewTraceFromExemplar(traceId) {
    // Switch to traces tab and show trace detail
    import('./tabs.js').then(module => {
        module.switchTab('traces');
    });

    // Load and show trace
    setTimeout(() => {
        import('./traces.js').then(module => {
            module.showTraceDetail(traceId);
        });
    }, 100);
}

function calculatePercentilesFromBuckets(buckets, percentiles = [50, 75, 90, 95, 99]) {
    if (!buckets || buckets.length === 0) {
        return {};
    }

    // Calculate total count
    const totalCount = buckets.reduce((sum, b) => sum + (b.count || 0), 0);
    if (totalCount === 0) {
        return {};
    }

    // Build cumulative distribution
    const cumulative = [];
    let cumulativeCount = 0;
    let prevBound = 0;

    for (const bucket of buckets) {
        const bound = bucket.bound !== undefined ? bucket.bound :
            bucket.upper_bound !== undefined ? bucket.upper_bound :
                bucket.upperBound;
        const count = bucket.count || 0;

        cumulativeCount += count;

        // Handle infinity bound
        const upperBound = (bound === null || bound === undefined || bound === Infinity)
            ? prevBound * 2 || 1000  // Estimate for +Inf bucket
            : bound;

        cumulative.push({
            upperBound: upperBound,
            cumulativeCount: cumulativeCount,
            lowerBound: prevBound
        });

        prevBound = upperBound;
    }

    // Calculate each percentile using linear interpolation
    const result = {};

    for (const p of percentiles) {
        const targetCount = (p / 100) * totalCount;

        // Find the bucket containing this percentile
        let percentileValue = 0;

        for (let i = 0; i < cumulative.length; i++) {
            const bucket = cumulative[i];

            if (bucket.cumulativeCount >= targetCount) {
                // Found the bucket
                const prevCumulativeCount = i > 0 ? cumulative[i - 1].cumulativeCount : 0;
                const bucketRange = bucket.upperBound - bucket.lowerBound;
                const countInBucket = bucket.cumulativeCount - prevCumulativeCount;
                const countIntoBucket = targetCount - prevCumulativeCount;

                // Linear interpolation within bucket
                if (countInBucket > 0) {
                    const ratio = countIntoBucket / countInBucket;
                    percentileValue = bucket.lowerBound + (ratio * bucketRange);
                } else {
                    percentileValue = bucket.lowerBound;
                }

                break;
            }
        }

        result[`p${p}`] = percentileValue;
    }

    return result;
}

function buildSeriesLabel(series, allSeries = []) {
    const parts = [];

    // Check if all series have the same resource attributes
    // If so, don't include them in the label (they're not distinguishing)
    const includeResources = allSeries.length > 1 && !allSeriesHaveSameResources(allSeries);

    // Add key resource attributes only if they distinguish series
    if (includeResources && series.resource) {
        const serviceName = series.resource['service.name'];
        if (serviceName) parts.push(serviceName);

        const hostName = series.resource['host.name'];
        if (hostName && hostName !== serviceName) parts.push(hostName);
    }

    // Add ALL metric attributes (these usually distinguish series)
    if (series.attributes) {
        // Sort attributes by key for consistent ordering
        const sortedAttrs = Object.entries(series.attributes).sort(([a], [b]) => a.localeCompare(b));

        for (const [key, value] of sortedAttrs) {
            // Skip service.name if it's already in resources
            if (key === 'service.name' && includeResources) continue;

            // Format the attribute as key=value
            parts.push(`${key}=${value}`);
        }
    }

    return parts.length > 0 ? parts.join(', ') : 'Series';
}

function allSeriesHaveSameResources(allSeries) {
    if (allSeries.length <= 1) return true;

    const firstResource = JSON.stringify(allSeries[0].resource || {});
    return allSeries.every(s => JSON.stringify(s.resource || {}) === firstResource);
}

function calculatePercentile(histogram, percentile) {
    const target = percentile === 'p50' ? 50 : percentile === 'p95' ? 95 : 99;
    const totalCount = histogram.count || 0;

    if (!histogram.bucketCounts || !histogram.explicitBounds || totalCount === 0) {
        return 0;
    }

    const targetCount = (target / 100) * totalCount;
    let cumulative = 0;
    let prevBound = 0;

    for (let i = 0; i < histogram.bucketCounts.length; i++) {
        cumulative += histogram.bucketCounts[i];

        if (cumulative >= targetCount) {
            const bound = histogram.explicitBounds[i] || prevBound * 2;
            const bucketCount = histogram.bucketCounts[i];

            if (bucketCount > 0) {
                const prevCum = cumulative - bucketCount;
                const fraction = (targetCount - prevCum) / bucketCount;
                return prevBound + fraction * (bound - prevBound);
            }
            return prevBound;
        }

        prevBound = histogram.explicitBounds[i] || prevBound;
    }

    return prevBound;
}

function adjustColorAlpha(color, alpha) {
    return color + Math.floor(alpha * 255).toString(16).padStart(2, '0');
}

// Global window functions for filters
window.removeResourceFilter = (key) => {
    delete activeResourceFilters[key];
    import('./api.js').then(module => module.loadMetrics());
};

window.clearAllResourceFilters = () => {
    activeResourceFilters = {};
    import('./api.js').then(module => module.loadMetrics());
};

window.showResourceValueInput = (key) => {
    if (!key) return;
    const value = prompt(`Enter value for ${key}:`);
    if (value) {
        activeResourceFilters[key] = value;
        import('./api.js').then(module => module.loadMetrics());
    }
    document.getElementById('resource-key-select').value = '';
};

window.applyAttributeFilter = (chartId, key, value) => {
    // Re-render chart with filtered series
    // This is a simplified version - full implementation would store filters and re-fetch
    console.log(`Filter ${key}=${value} for chart ${chartId}`);
};

export function isMetricChartOpen() {
    return expandedMetric !== null;
}

// === Global Correlation Functions ===

window.viewMetricsForService = (serviceName, startTime, endTime) => {
    if (!serviceName) return;

    // Set resource filter for service.name
    activeResourceFilters = {
        'service.name': serviceName
    };

    // Switch to metrics tab
    import('./tabs.js').then(module => {
        module.switchTab('metrics');
    });

    // Load metrics and auto-expand first duration metric
    setTimeout(async () => {
        const api = await import('./api.js');
        await api.loadMetrics();

        // After metrics are loaded, find and expand the first duration metric
        setTimeout(() => {
            // Look for traces.span.duration or similar duration metric
            const metricRows = document.querySelectorAll('.metric-row');
            let targetRow = null;

            for (const row of metricRows) {
                const metricName = row.dataset.metricName;
                if (metricName) {
                    // Prefer duration metrics first
                    if (metricName.includes('duration') || metricName.includes('latency')) {
                        targetRow = row;
                        break;
                    }
                    // Fallback to first metric
                    if (!targetRow) {
                        targetRow = row;
                    }
                }
            }

            // Expand the target metric by clicking its header
            if (targetRow) {
                const header = targetRow.querySelector('.metric-header');
                if (header) {
                    header.click();
                }
            }
        }, 300);
    }, 100);
};

window.viewMetricsForTrace = (traceId) => {
    // This function can be called from trace exemplars
    // For now, just switch to metrics tab
    import('./tabs.js').then(module => {
        module.switchTab('metrics');
    });

    setTimeout(() => {
        import('./api.js').then(module => module.loadMetrics());
    }, 100);
};

window.viewMetricsWithFilters = (filters) => {
    if (!filters) return;

    // Set resource filters
    if (filters.resource) {
        activeResourceFilters = { ...filters.resource };
    }

    // TODO: Store attribute filters for use when metric is expanded
    // For now, just apply resource filters

    // Switch to metrics tab
    import('./tabs.js').then(module => {
        module.switchTab('metrics');
    });

    // Load metrics with filters
    setTimeout(() => {
        import('./api.js').then(module => module.loadMetrics());
    }, 100);
};

window.viewTraceFromExemplar = (traceId) => {
    // Switch to traces tab and show trace detail
    import('./tabs.js').then(module => {
        module.switchTab('traces');
    });

    // Load and show trace
    setTimeout(() => {
        import('./traces.js').then(module => {
            module.showTraceDetail(traceId);
        });
    }, 200);
};

window.toggleREDMetricsFilter = () => {
    showOnlyRED = !showOnlyRED;
    // Re-render metrics with new filter
    renderMetrics(allMetrics);
};

window.closeAllMetrics = () => {
    // Close all expanded metrics
    document.querySelectorAll('.metric-detail-container').forEach(container => {
        if (container.style.display !== 'none') {
            const row = container.closest('.metric-row');
            if (row) {
                const header = row.querySelector('.metric-header');
                if (header) {
                    header.click(); // Toggle to close
                }
            }
        }
    });
    expandedMetric = null;
};

window.showMetricResources = async (metricName, resourceCount) => {
    try {
        const response = await fetch(`/api/metrics/${metricName}`);
        const data = await response.json();

        if (!data.series || data.series.length === 0) {
            createModal('Metric Resources', '<p>No resource data available</p>', [
                { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
            ]);
            return;
        }

        // Extract unique resources
        const resourcesMap = new Map();
        data.series.forEach(series => {
            if (series.resource) {
                const resourceKey = JSON.stringify(series.resource);
                if (!resourcesMap.has(resourceKey)) {
                    resourcesMap.set(resourceKey, series.resource);
                }
            }
        });

        let contentHtml = `<div style="max-height: 400px; overflow-y: auto;">`;
        contentHtml += `<p style="margin-bottom: 10px;"><strong>Found ${resourcesMap.size} unique resource(s):</strong></p>`;

        let index = 1;
        resourcesMap.forEach((resource) => {
            contentHtml += `<div style="margin-bottom: 15px; padding: 10px; background: var(--bg-hover); border-radius: 4px;">`;
            contentHtml += `<div style="font-weight: 600; margin-bottom: 5px;">Resource ${index}:</div>`;
            contentHtml += `<table style="width: 100%; font-size: 12px;">`;

            Object.entries(resource).forEach(([key, value]) => {
                contentHtml += `<tr><td style="padding: 2px 5px; color: var(--text-muted);">${key}:</td><td style="padding: 2px 5px;">${value}</td></tr>`;
            });

            contentHtml += `</table></div>`;
            index++;
        });

        contentHtml += `</div>`;

        createModal(`Resources for ${metricName}`, contentHtml, [
            { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
        ]);
    } catch (error) {
        console.error('Error loading metric resources:', error);
        createModal('Error', '<p>Failed to load metric resources</p>', [
            { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
        ]);
    }
};

window.showMetricAttributes = async (metricName, attributeCount) => {
    try {
        const response = await fetch(`/api/metrics/${metricName}`);
        const data = await response.json();

        if (!data.series || data.series.length === 0) {
            createModal('Metric Attributes', '<p>No attribute data available</p>', [
                { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
            ]);
            return;
        }

        // Extract unique attribute combinations
        const attributesMap = new Map();
        data.series.forEach(series => {
            if (series.attributes) {
                const attrKey = JSON.stringify(series.attributes);
                if (!attributesMap.has(attrKey)) {
                    attributesMap.set(attrKey, series.attributes);
                }
            }
        });

        let contentHtml = `<div style="max-height: 400px; overflow-y: auto;">`;
        contentHtml += `<p style="margin-bottom: 10px;"><strong>Found ${attributesMap.size} unique attribute combination(s):</strong></p>`;

        let index = 1;
        attributesMap.forEach((attributes) => {
            contentHtml += `<div style="margin-bottom: 15px; padding: 10px; background: var(--bg-hover); border-radius: 4px;">`;
            contentHtml += `<div style="font-weight: 600; margin-bottom: 5px;">Combination ${index}:</div>`;
            contentHtml += `<table style="width: 100%; font-size: 12px;">`;

            Object.entries(attributes).forEach(([key, value]) => {
                contentHtml += `<tr><td style="padding: 2px 5px; color: var(--text-muted);">${key}:</td><td style="padding: 2px 5px;">${value}</td></tr>`;
            });

            contentHtml += `</table></div>`;
            index++;
        });

        contentHtml += `</div>`;

        createModal(`Attributes for ${metricName}`, contentHtml, [
            { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
        ]);
    } catch (error) {
        console.error('Error loading metric attributes:', error);
        createModal('Error', '<p>Failed to load metric attributes</p>', [
            { id: 'close', label: 'Close', style: 'secondary', handler: (modal) => closeModal(modal) }
        ]);
    }
};
