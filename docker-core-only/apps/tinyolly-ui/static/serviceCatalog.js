/**
 * Service Catalog Module - Displays services with RED metrics and inline charts
 */
import { formatTime, formatDuration, loadChartJs, escapeHtml, attachHoverEffects, renderEmptyState, sortItems, getSortIndicator, destroyChart, closeAllExpandedItems } from './utils.js';

const chartInstances = {};
const openCharts = new Map(); // Track which charts are open: serviceName -> {metricType, metricName, metricTypeLabel}
let currentSort = { column: 'name', direction: 'asc' }; // Track current sort

export function renderServiceCatalog(services) {
    const container = document.getElementById('catalog-container');
    if (!container) return;

    if (!services || services.length === 0) {
        container.innerHTML = renderEmptyState('📋', 'No services found. Generate some traces to populate the catalog.');
        return;
    }

    // Sort services based on current sort settings
    sortItems(services, currentSort.column, currentSort.direction);

    const limitNote = `<div style="text-align: center; padding: 10px; font-size: 12px; color: var(--text-muted);">Showing ${services.length} service${services.length !== 1 ? 's' : ''}</div>`;

    const headerRow = `
        <div class="catalog-header-row" style="display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            <div data-sort="name" style="flex: 0 0 200px; cursor: pointer; user-select: none;" title="Click to sort">Service Name ${getSortIndicator('name', currentSort)}</div>
            <div data-sort="rate" style="flex: 0 0 80px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">Rate ${getSortIndicator('rate', currentSort)}</div>
            <div data-sort="error_rate" style="flex: 0 0 70px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">Errors ${getSortIndicator('error_rate', currentSort)}</div>
            <div data-sort="duration_p50" style="flex: 0 0 70px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">P50 ${getSortIndicator('duration_p50', currentSort)}</div>
            <div data-sort="duration_p95" style="flex: 0 0 70px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">P95 ${getSortIndicator('duration_p95', currentSort)}</div>
            <div data-sort="span_count" style="flex: 0 0 80px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">Spans ${getSortIndicator('span_count', currentSort)}</div>
            <div data-sort="trace_count" style="flex: 0 0 80px; text-align: right; cursor: pointer; user-select: none;" title="Click to sort">Traces ${getSortIndicator('trace_count', currentSort)}</div>
            <div data-sort="first_seen" style="flex: 0 0 100px; cursor: pointer; user-select: none;" title="Click to sort">First Seen ${getSortIndicator('first_seen', currentSort)}</div>
            <div data-sort="last_seen" style="flex: 0 0 100px; cursor: pointer; user-select: none;" title="Click to sort">Last Seen ${getSortIndicator('last_seen', currentSort)}</div>
            <div style="flex: 1;">Actions</div>
        </div>
    `;

    const servicesHtml = services.map((service, index) => {
        const firstSeen = formatTime(service.first_seen);
        const lastSeen = formatTime(service.last_seen);
        const serviceId = `service-${index}`;

        // Format RED metrics
        const rate = service.rate !== null ? `${service.rate}/s` : '-';
        const errorRate = service.error_rate !== null ? `${service.error_rate}%` : '-';
        const p50 = service.duration_p50 !== null ? formatDuration(service.duration_p50) : '-';
        const p95 = service.duration_p95 !== null ? formatDuration(service.duration_p95) : '-';

        // Color code error rate
        let errorColor = 'var(--text-main)';
        if (service.error_rate !== null) {
            if (service.error_rate > 5) errorColor = '#ef4444'; // Red
            else if (service.error_rate > 1) errorColor = '#f59e0b'; // Orange
            else errorColor = '#10b981'; // Green
        }

        return `
            <div class="catalog-service-row" data-service-id="${serviceId}">
                <div class="catalog-item" style="display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 11px; transition: background 0.2s; cursor: pointer;">
                    <div style="flex: 0 0 200px; font-weight: 600; color: var(--text-main); font-size: 14px;">${escapeHtml(service.name)}</div>
                    <div data-metric="calls" data-service="${escapeHtml(service.name)}" style="flex: 0 0 80px; text-align: right; color: var(--primary); font-family: monospace; font-weight: 600; cursor: pointer; text-decoration: underline; text-decoration-style: dotted;" title="Click to view metric">${rate}</div>
                    <div data-metric="calls" data-service="${escapeHtml(service.name)}" style="flex: 0 0 70px; text-align: right; color: ${errorColor}; font-family: monospace; font-weight: 600; cursor: pointer; text-decoration: underline; text-decoration-style: dotted;" title="Click to view metric">${errorRate}</div>
                    <div data-metric="duration" data-service="${escapeHtml(service.name)}" style="flex: 0 0 70px; text-align: right; color: var(--text-main); font-family: monospace; cursor: pointer; text-decoration: underline; text-decoration-style: dotted;" title="Click to view metric">${p50}</div>
                    <div data-metric="duration" data-service="${escapeHtml(service.name)}" style="flex: 0 0 70px; text-align: right; color: var(--text-main); font-family: monospace; cursor: pointer; text-decoration: underline; text-decoration-style: dotted;" title="Click to view metric">${p95}</div>
                    <div style="flex: 0 0 80px; text-align: right; color: var(--text-muted); font-family: monospace; font-size: 12px;">${service.span_count.toLocaleString()}</div>
                    <div style="flex: 0 0 80px; text-align: right; color: var(--text-muted); font-family: monospace; font-size: 12px;">${service.trace_count.toLocaleString()}</div>
                    <div style="flex: 0 0 100px; font-family: monospace; color: var(--text-muted); font-size: 11px;">${firstSeen}</div>
                    <div style="flex: 0 0 100px; font-family: monospace; color: var(--text-muted); font-size: 11px;">${lastSeen}</div>
                    <div style="flex: 1; display: flex; gap: 8px;">
                        <button onclick="viewServiceSpans('${escapeHtml(service.name)}')" style="padding: 4px 12px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: background 0.2s;">
                            Spans
                        </button>
                        <button onclick="viewServiceLogs('${escapeHtml(service.name)}')" style="padding: 4px 12px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: background 0.2s;">
                            Logs
                        </button>
                        <button onclick="window.viewMetricsForService('${escapeHtml(service.name)}')" style="padding: 4px 12px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: background 0.2s;">
                            Metrics
                        </button>
                    </div>
                </div>
                <div class="catalog-chart-container" style="display: none; padding: 20px; background: var(--bg-secondary); border-bottom: 1px solid var(--border);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div class="chart-header" style="font-size: 13px; color: var(--text-muted);"></div>
                        <button class="chart-close-btn" style="padding: 4px 12px; background: transparent; color: var(--text-muted); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; font-size: 11px; transition: all 0.2s;" onmouseover="this.style.background='var(--bg-hover)'; this.style.color='var(--text-main)';" onmouseout="this.style.background='transparent'; this.style.color='var(--text-muted)';">Close</button>
                    </div>
                    <div style="position: relative; height: 200px;">
                        <canvas id="chart-${serviceId}"></canvas>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = limitNote + headerRow + servicesHtml;

    // Add hover effect and click handlers
    const items = container.querySelectorAll('.catalog-item');
    attachHoverEffects(items);

    // Add click handlers for RED metric values
    const metricCells = container.querySelectorAll('[data-metric]');
    metricCells.forEach(cell => {
        cell.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricType = cell.getAttribute('data-metric');
            const serviceName = cell.getAttribute('data-service');
            const serviceRow = cell.closest('.catalog-service-row');
            const serviceId = serviceRow.getAttribute('data-service-id');
            const chartContainer = serviceRow.querySelector('.catalog-chart-container');
            const chartHeader = serviceRow.querySelector('.chart-header');
            const canvas = serviceRow.querySelector('canvas');

            // Toggle chart visibility
            if (chartContainer.style.display === 'none') {
                // Clear any existing active states in this row
                const allCellsInRow = serviceRow.querySelectorAll('[data-metric]');
                allCellsInRow.forEach(c => {
                    c.style.background = '';
                    c.style.padding = '';
                    c.style.borderRadius = '';
                });

                // Show and load chart
                chartContainer.style.display = 'block';

                // Highlight the clicked cell
                cell.style.background = 'var(--bg-hover)';
                cell.style.padding = '4px 8px';
                cell.style.borderRadius = '4px';

                const metricName = metricType === 'calls'
                    ? 'traces.span.metrics.calls'
                    : 'traces.span.metrics.duration';

                const metricTypeLabel = metricType === 'calls' ? 'Counter' : 'Histogram';

                // Save state
                openCharts.set(serviceName, { metricType, metricName, metricTypeLabel });

                // Load Chart.js and render
                await loadChartJs();
                await renderServiceMetricChart(canvas, metricName, serviceName, serviceId, chartHeader, metricTypeLabel);
            } else {
                // If clicking the same cell, close it
                // If clicking a different cell, switch to that metric
                const currentMetricType = openCharts.get(serviceName)?.metricType;

                if (currentMetricType === metricType) {
                    // Close the chart
                    closeChart(serviceRow, serviceName, canvas);
                } else {
                    // Switch to different metric
                    // Clear previous highlights
                    const allCellsInRow = serviceRow.querySelectorAll('[data-metric]');
                    allCellsInRow.forEach(c => {
                        c.style.background = '';
                        c.style.padding = '';
                        c.style.borderRadius = '';
                    });

                    // Highlight new cell
                    cell.style.background = 'var(--bg-hover)';
                    cell.style.padding = '4px 8px';
                    cell.style.borderRadius = '4px';

                    const metricName = metricType === 'calls'
                        ? 'traces.span.metrics.calls'
                        : 'traces.span.metrics.duration';

                    const metricTypeLabel = metricType === 'calls' ? 'Counter' : 'Histogram';

                    // Update state
                    openCharts.set(serviceName, { metricType, metricName, metricTypeLabel });

                    // Re-render chart
                    await loadChartJs();
                    await renderServiceMetricChart(canvas, metricName, serviceName, serviceId, chartHeader, metricTypeLabel);
                }
            }
        });
    });

    // Add click handlers for close buttons
    const closeButtons = container.querySelectorAll('.chart-close-btn');
    closeButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const serviceRow = btn.closest('.catalog-service-row');
            const canvas = serviceRow.querySelector('canvas');

            // Get service name from any metric cell
            const metricCell = serviceRow.querySelector('[data-metric]');
            const serviceName = metricCell ? metricCell.getAttribute('data-service') : null;

            if (serviceName) {
                closeChart(serviceRow, serviceName, canvas);
            }
        });
    });

    // Add click handlers for sortable headers
    const sortHeaders = container.querySelectorAll('[data-sort]');
    sortHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const column = header.getAttribute('data-sort');

            // Toggle direction if clicking the same column
            if (currentSort.column === column) {
                currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.column = column;
                currentSort.direction = 'asc';
            }

            // Re-render with new sort
            import('./api.js').then(module => {
                module.loadServiceCatalog();
            });
        });
    });

    // Restore previously open charts after rendering
    restoreOpenCharts(services);
}

function closeChart(serviceRow, serviceName, canvas) {
    const chartContainer = serviceRow.querySelector('.catalog-chart-container');

    // Hide chart
    chartContainer.style.display = 'none';

    // Remove highlight from all metric cells
    const allCellsInRow = serviceRow.querySelectorAll('[data-metric]');
    allCellsInRow.forEach(c => {
        c.style.background = '';
        c.style.padding = '';
        c.style.borderRadius = '';
    });

    // Remove state
    openCharts.delete(serviceName);

    // Destroy chart instance if exists
    const chartId = canvas.id;
    if (chartInstances[chartId]) {
        chartInstances[chartId].destroy();
        delete chartInstances[chartId];
    }
}

async function renderServiceMetricChart(canvas, metricName, serviceName, serviceId, chartHeader, metricTypeLabel) {
    const chartId = canvas.id;

    try {
        // Fetch metric data
        const endTime = Date.now() / 1000;
        const startTime = endTime - 600; // Last 10 minutes

        const response = await fetch(`/api/metrics/${metricName}?start=${startTime}&end=${endTime}`);
        const data = await response.json();

        if (!data.series || data.series.length === 0) {
            chartHeader.textContent = `${metricTypeLabel}: ${metricName} (No data)`;
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = 'var(--text-muted)';
            ctx.font = '12px Inter';
            ctx.textAlign = 'center';
            ctx.fillText('No data available', canvas.width / 2, 100);
            return;
        }

        // Filter series for this service (check both resource and attributes)
        const serviceSeries = data.series.filter(series => {
            const serviceFromResource = series.resource?.['service.name'];
            const serviceFromAttr = series.attributes?.['service.name'];
            return serviceFromResource === serviceName || serviceFromAttr === serviceName;
        });

        if (serviceSeries.length === 0) {
            chartHeader.textContent = `${metricTypeLabel}: ${metricName} (No data for ${serviceName})`;
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = 'var(--text-muted)';
            ctx.font = '12px Inter';
            ctx.textAlign = 'center';
            ctx.fillText('No data available for this service', canvas.width / 2, 100);
            return;
        }

        // Get labels from first matching series
        const firstSeries = serviceSeries[0];
        const labels = { ...(firstSeries.resource || {}), ...(firstSeries.attributes || {}) };
        const labelStr = Object.entries(labels)
            .filter(([k, v]) => k !== 'service.name') // Exclude service.name from label string
            .map(([k, v]) => `${k}="${v}"`)
            .join(', ');
        const labelSuffix = labelStr ? `{${labelStr}}` : '';
        chartHeader.textContent = `${metricTypeLabel}: ${metricName}${labelSuffix}`;

        // Destroy existing chart if any
        if (chartInstances[chartId]) {
            chartInstances[chartId].destroy();
        }

        // Determine if this is a histogram or counter by checking first datapoint
        const firstDatapoint = firstSeries.datapoints?.[0];
        const isHistogram = firstDatapoint?.histogram !== undefined && firstDatapoint?.histogram !== null;

        if (isHistogram) {
            // Aggregate histogram buckets from all series for this service
            // Get the latest datapoint from the first series (or aggregate across all)
            let latestDatapoint = null;
            for (const series of serviceSeries) {
                if (series.datapoints && series.datapoints.length > 0) {
                    const latest = series.datapoints[series.datapoints.length - 1];
                    if (!latestDatapoint || (latest.timestamp > latestDatapoint.timestamp)) {
                        latestDatapoint = latest;
                    }
                }
            }

            if (!latestDatapoint || !latestDatapoint.histogram) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = 'var(--text-muted)';
                ctx.font = '12px Inter';
                ctx.textAlign = 'center';
                ctx.fillText('No histogram data available', canvas.width / 2, 100);
                return;
            }

            // Convert normalized histogram format (bucketCounts + explicitBounds) to buckets array
            const bucketCounts = latestDatapoint.histogram.bucketCounts || [];
            const explicitBounds = latestDatapoint.histogram.explicitBounds || [];

            if (bucketCounts.length === 0) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = 'var(--text-muted)';
                ctx.font = '12px Inter';
                ctx.textAlign = 'center';
                ctx.fillText('No histogram buckets available', canvas.width / 2, 100);
                return;
            }

            // Build buckets array from bucketCounts and explicitBounds
            const buckets = bucketCounts.map((count, idx) => ({
                count: count,
                bound: idx < explicitBounds.length ? explicitBounds[idx] : null
            }));

            const labels = buckets.map(b => {
                const bound = b.bound;
                if (bound === null || bound === undefined || bound === Infinity) {
                    return '∞';
                }
                return bound.toFixed(2);
            });

            const counts = buckets.map(b => b.count || 0);

            chartInstances[chartId] = new Chart(canvas, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Count',
                        data: counts,
                        backgroundColor: 'rgba(59, 130, 246, 0.6)',
                        borderColor: 'rgb(59, 130, 246)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function (context) {
                                    const label = context.label === '∞' ? '> previous bound' : `≤ ${context.label}ms`;
                                    return `Count: ${context.parsed.y} ${label}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            display: true,
                            title: {
                                display: true,
                                text: 'Upper Bound (ms)'
                            },
                            grid: { display: false }
                        },
                        y: {
                            display: true,
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Request Count'
                            },
                            grid: {
                                color: 'rgba(0, 0, 0, 0.1)'
                            },
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
        } else {
            // Counter - show rate over time (aggregate across all series for this service)
            // Group by timestamp and sum values from all series
            const timeMap = new Map();
            for (const series of serviceSeries) {
                if (!series.datapoints) continue;
                for (const datapoint of series.datapoints) {
                    const ts = datapoint.timestamp;
                    const value = datapoint.value || 0;
                    if (!timeMap.has(ts)) {
                        timeMap.set(ts, 0);
                    }
                    timeMap.set(ts, timeMap.get(ts) + value);
                }
            }

            // Sort by timestamp
            const sortedTimes = Array.from(timeMap.keys()).sort((a, b) => a - b);

            if (sortedTimes.length === 0) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = 'var(--text-muted)';
                ctx.font = '12px Inter';
                ctx.textAlign = 'center';
                ctx.fillText('No counter data available', canvas.width / 2, 100);
                return;
            }

            const labels = [];
            const rates = [];

            for (let i = 1; i < sortedTimes.length; i++) {
                const prevTime = sortedTimes[i - 1];
                const currTime = sortedTimes[i];

                const prevValue = timeMap.get(prevTime);
                const currValue = timeMap.get(currTime);
                const timeDelta = currTime - prevTime;

                let rate = 0;
                if (timeDelta > 0) {
                    const valueDelta = currValue - prevValue;
                    const actualDelta = valueDelta >= 0 ? valueDelta : currValue;
                    rate = actualDelta / timeDelta;
                }

                const date = new Date(currTime * 1000);
                labels.push(date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
                rates.push(rate);
            }

            chartInstances[chartId] = new Chart(canvas, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Requests per second',
                        data: rates,
                        borderColor: 'rgb(59, 130, 246)',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 1,
                        pointHoverRadius: 3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                label: function (context) {
                                    return `${context.parsed.y.toFixed(2)} req/sec`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            display: true,
                            grid: { display: false },
                            ticks: {
                                maxTicksLimit: 8,
                                maxRotation: 0
                            }
                        },
                        y: {
                            display: true,
                            beginAtZero: true,
                            grace: '10%',
                            grid: {
                                color: 'rgba(0, 0, 0, 0.1)'
                            },
                            ticks: {
                                callback: function (value) {
                                    return value.toFixed(1) + '/s';
                                }
                            }
                        }
                    }
                }
            });
        }
    } catch (error) {
        console.error(`Error rendering chart for ${metricName}:`, error);
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'var(--text-muted)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('Error loading chart', canvas.width / 2, 100);
    }
}

async function restoreOpenCharts(services) {
    // Re-open charts that were previously open
    if (openCharts.size === 0) return;

    // Wait a tick for DOM to be ready
    await new Promise(resolve => setTimeout(resolve, 0));

    for (const [serviceName, chartInfo] of openCharts.entries()) {
        // Find the service in the new render
        const service = services.find(s => s.name === serviceName);
        if (!service) {
            // Service no longer exists, remove from tracking
            openCharts.delete(serviceName);
            continue;
        }

        // Find the service row
        const serviceRows = document.querySelectorAll('.catalog-service-row');
        let targetRow = null;
        for (const row of serviceRows) {
            const serviceCells = row.querySelectorAll('[data-service]');
            for (const cell of serviceCells) {
                if (cell.getAttribute('data-service') === serviceName) {
                    targetRow = row;
                    break;
                }
            }
            if (targetRow) break;
        }

        if (!targetRow) continue;

        const serviceId = targetRow.getAttribute('data-service-id');
        const chartContainer = targetRow.querySelector('.catalog-chart-container');
        const chartHeader = targetRow.querySelector('.chart-header');
        const canvas = targetRow.querySelector('canvas');

        if (!chartContainer || !canvas) continue;

        // Show chart container
        chartContainer.style.display = 'block';

        // Highlight the active metric cell
        const metricCells = targetRow.querySelectorAll(`[data-metric="${chartInfo.metricType}"]`);
        if (metricCells.length > 0) {
            metricCells[0].style.background = 'var(--bg-hover)';
            metricCells[0].style.padding = '4px 8px';
            metricCells[0].style.borderRadius = '4px';
        }

        // Render the chart
        await loadChartJs();
        await renderServiceMetricChart(
            canvas,
            chartInfo.metricName,
            serviceName,
            serviceId,
            chartHeader,
            chartInfo.metricTypeLabel
        );
    }
}

// Global functions for button actions
window.viewServiceSpans = function (serviceName) {
    // Set search input BEFORE switching tabs so renderSpans() will apply it
    const searchInput = document.getElementById('span-search');
    if (searchInput) {
        searchInput.value = serviceName;
    }

    // Now switch to spans tab (which will load and render, applying the filter)
    if (window.switchTab) {
        window.switchTab('spans');
    }
};

window.viewServiceLogs = function (serviceName) {
    // Set search input BEFORE switching tabs so renderLogs() will apply it
    const searchInput = document.getElementById('log-search');
    if (searchInput) {
        searchInput.value = serviceName;
    }

    // Now switch to logs tab (which will load and render, applying the filter)
    if (window.switchTab) {
        window.switchTab('logs');
    }
};


// Close all expanded service charts
window.closeAllServiceCharts = () => {
    document.querySelectorAll('.catalog-service-row').forEach(serviceRow => {
        const chartContainer = serviceRow.querySelector('.catalog-chart-container');
        const canvas = serviceRow.querySelector('canvas');
        const metricCell = serviceRow.querySelector('[data-metric]');
        const serviceName = metricCell ? metricCell.getAttribute('data-service') : null;

        if (chartContainer && chartContainer.style.display !== 'none') {
            // Hide chart
            chartContainer.style.display = 'none';

            // Remove highlight from all metric cells
            const allCellsInRow = serviceRow.querySelectorAll('[data-metric]');
            allCellsInRow.forEach(c => {
                c.style.background = '';
                c.style.padding = '';
                c.style.borderRadius = '';
            });

            // Remove state
            if (serviceName) {
                openCharts.delete(serviceName);
            }

            // Destroy chart instance if exists
            if (canvas) {
                destroyChart(canvas.id, chartInstances);
            }
        }
    });
};
