/**
 * Render Module - Re-exports rendering functions from specialized modules
 */
export { renderTraces, showTraceDetail, showTracesList, toggleTraceJSON, copyTraceJSON, downloadTraceJSON, showLogsForTrace } from './traces.js';
export { renderSpans, isSpanDetailOpen, filterSpans } from './spans.js';
export { renderLogs, clearLogFilter, filterLogs, isLogJsonOpen } from './logs.js';
export { renderMetrics, isMetricChartOpen } from './metrics.js';
export { renderServiceMap } from './serviceMap.js';

export function renderStats(stats) {
    // Stats no longer displayed in UI
}
