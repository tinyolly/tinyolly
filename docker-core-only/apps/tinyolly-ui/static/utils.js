/** Utils Module - Shared formatting and data manipulation functions across all UI modules */

/** Converts nanosecond timestamp to HH:mm:ss.SSS format */
export function formatTime(ns) {
    const d = new Date(ns / 1000000);
    return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
}

/** Strips leading zeros from trace/span IDs for cleaner display */
export function formatTraceId(id) {
    return id.replace(/^0+(?=.)/, '');
}

/** Formats duration in ms to appropriate unit (µs/ms/s) */
export function formatDuration(ms) {
    if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`;
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
}

/** Generates stable ID for log entries combining timestamp and message prefix */
export function getLogStableId(log) {
    return `${log.timestamp}-${log.message}`.substring(0, 50);
}

/** Copies text to clipboard and displays temporary feedback message */
export function copyToClipboard(text, feedbackElement) {
    navigator.clipboard.writeText(text).then(() => {
        feedbackElement.style.display = 'inline';
        setTimeout(() => {
            feedbackElement.style.display = 'none';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
        feedbackElement.textContent = 'Copy failed';
        feedbackElement.style.color = 'var(--error)';
        feedbackElement.style.display = 'inline';
    });
}

/** Downloads JSON data as a file with specified filename */
export function downloadJson(data, filename) {
    const jsonContent = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/** Debounces function execution to prevent rapid consecutive calls */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

let chartJsPromise = null;

/** Lazy loads Chart.js and date-fns adapter libraries, returns cached promise if already loading */
export function loadChartJs() {
    if (window.Chart && window.Chart._adapters) {
        return Promise.resolve(window.Chart);
    }

    if (chartJsPromise) {
        return chartJsPromise;
    }

    chartJsPromise = new Promise((resolve, reject) => {
        // Load Chart.js first
        const chartScript = document.createElement('script');
        chartScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
        
        chartScript.onload = () => {
            // Then load the date adapter for time scales
            const adapterScript = document.createElement('script');
            adapterScript.src = 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js';
            adapterScript.onload = () => resolve(window.Chart);
            adapterScript.onerror = () => reject(new Error('Failed to load Chart.js date adapter'));
            document.head.appendChild(adapterScript);
        };
        
        chartScript.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(chartScript);
    });

    return chartJsPromise;
}

/** Converts Unix seconds timestamp to HH:mm:ss.SSS format */
export function formatTimestamp(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3
    });
}

/** Returns color for HTTP status code (green=2xx, orange=4xx, red=5xx) */
export function getStatusCodeColor(status) {
    if (!status) return 'var(--text-muted)';
    const s = String(status);
    if (s.startsWith('2') || s === 'OK') return 'var(--success)';
    if (s.startsWith('4')) return '#f59e0b';
    if (s.startsWith('5') || s === 'ERR') return 'var(--error)';
    return 'var(--text-muted)';
}

/** Formats span route/URL with styled protocol/host prefix and pathname */
export function formatRoute(span) {
    // Handle trace root span object structure which might have different keys
    const urlStr = span.url || span.root_span_url;
    const serverName = span.server_name || span.host || span.root_span_server_name || span.root_span_host;
    const scheme = span.scheme || span.root_span_scheme;
    const target = span.target || span.route || span.root_span_target || span.root_span_route;

    if (urlStr) {
        try {
            const url = new URL(urlStr);
            return `<span style="color: var(--text-muted); font-weight: normal;">${url.protocol}//${url.host}</span>${url.pathname}${url.search}`;
        } catch (e) {
            return urlStr;
        }
    } else if (serverName) {
        const schemeStr = scheme ? scheme + '://' : '';
        return `<span style="color: var(--text-muted); font-weight: normal;">${schemeStr}${serverName}</span>${target || ''}`;
    }
    return span.route || span.name || span.root_span_route || span.root_span_name || '';
}

/** Renders JSON data in styled detail view with title and action buttons */
export function renderJsonDetailView(data, title, buttonsHtml) {
    return `
        <div class="json-detail-view" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin: 12px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color);">
                <div style="font-size: 14px; font-weight: 600; color: var(--text-main);">
                    ${title}
                </div>
                <div style="display: flex; gap: 8px;">
                    ${buttonsHtml}
                </div>
            </div>
            <div style="background: var(--bg-hover); border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; overflow: auto; max-height: 500px;">
                <pre style="font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-main); margin: 0; white-space: pre-wrap; word-wrap: break-word; line-height: 1.5;">${JSON.stringify(data, null, 2)}</pre>
            </div>
        </div>
    `;
}


/** Returns color for log severity level (red=ERROR, orange=WARN, blue=INFO, purple=DEBUG) */
export function getSeverityColor(severity) {
    if (!severity) return 'var(--text-muted)';
    const s = String(severity).toUpperCase();
    if (s === 'ERROR' || s === 'CRITICAL' || s === 'FATAL') return 'var(--error)';
    if (s === 'WARN' || s === 'WARNING') return '#f59e0b'; // Orange
    if (s === 'INFO') return 'var(--success)'; // Green/Blue depending on theme, using success for now
    if (s === 'DEBUG' || s === 'TRACE') return '#8b5cf6'; // Purple
    return 'var(--text-muted)';
}

/** Renders styled button with primary (blue) or secondary (gray) theme */
export function renderActionButton(id, label, style = 'secondary') {
    const isPrimary = style === 'primary';
    const buttonStyle = isPrimary
        ? 'padding: 6px 12px; cursor: pointer; border: 1px solid var(--primary); background: var(--primary); color: white; border-radius: 4px; font-size: 12px; font-weight: 500;'
        : 'padding: 6px 12px; cursor: pointer; border: 1px solid var(--border-color); background: var(--bg-secondary); color: var(--text-main); border-radius: 4px; font-size: 12px;';
    
    return `<button id="${id}" style="${buttonStyle}">${label}</button>`;
}

/** Renders empty state with icon and message */
export function renderEmptyState(icon, message) {
    return `<div class="empty"><div class="empty-icon">${icon}</div><div>${message}</div></div>`;
}

/** Renders error state with warning icon and message */
export function renderErrorState(message) {
    return `<div class="empty"><div class="empty-icon">⚠️</div><div>${message}</div></div>`;
}

/** Renders loading spinner with optional message */
export function renderLoadingState(message = 'Loading...') {
    return `<div class="loading">${message}</div>`;
}

/** Renders table header row with column definitions for consistent styling */
export function renderTableHeader(columns) {
    const columnsHtml = columns.map(col => {
        const align = col.align ? `text-align: ${col.align};` : '';
        return `<div style="flex: ${col.flex}; ${align}">${col.label}</div>`;
    }).join('');
    
    return `
        <div style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            ${columnsHtml}
        </div>
    `;
}

/** Escapes HTML special characters to prevent XSS attacks */
export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


/** Attaches hover background color effects to DOM elements */
export function attachHoverEffects(elements, hoverColor = 'var(--bg-hover)') {
    elements.forEach(el => {
        el.addEventListener('mouseenter', () => {
            el.style.background = hoverColor;
        });
        el.addEventListener('mouseleave', () => {
            el.style.background = 'transparent';
        });
    });
}


/** Filters table rows by search term across specified CSS selectors or entire row content */
export function filterTableRows(rows, searchTerm, selectors, displayStyle = 'flex') {
    const term = searchTerm.toLowerCase().trim();
    
    rows.forEach(row => {
        if (!term) {
            row.style.display = displayStyle;
            row.classList.remove('hidden');
            return;
        }
        
        let matches = false;
        
        // If selector is '*', search entire row text content
        if (selectors.length === 1 && selectors[0] === '*') {
            matches = row.textContent.toLowerCase().includes(term);
        } else {
            // Otherwise, search specific selectors
            matches = selectors.some(selector => {
                const element = row.querySelector(selector);
                return element && element.textContent.toLowerCase().includes(term);
            });
        }
        
        if (matches) {
            row.style.display = displayStyle;
            row.classList.remove('hidden');
        } else {
            row.style.display = 'none';
            row.classList.add('hidden');
        }
    });
}

/** Returns color from predefined palette by index (cycles through 10 colors) */
export function getColorForIndex(idx) {
    const colors = [
        '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
        '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'
    ];
    return colors[idx % colors.length];
}

/** Sorts array of objects by column in ascending or descending order (modifies in place) */
export function sortItems(items, column, direction = 'asc') {
    items.sort((a, b) => {
        let aVal = a[column];
        let bVal = b[column];
        
        // Handle null/undefined - put at end
        if (aVal === null || aVal === undefined) return 1;
        if (bVal === null || bVal === undefined) return -1;
        
        // Compare based on type
        let comparison = 0;
        if (typeof aVal === 'string') {
            comparison = aVal.localeCompare(bVal);
        } else {
            comparison = aVal - bVal;
        }
        
        return direction === 'asc' ? comparison : -comparison;
    });
    return items;
}

/** Extracts OTEL attribute value from span/log, checking multiple key formats */
export function getAttributeValue(item, keys) {
    const attributes = item.attributes || [];
    
    // Handle array format (OTEL)
    if (Array.isArray(attributes)) {
        for (const key of keys) {
            const attr = attributes.find(a => a.key === key);
            if (attr && attr.value) {
                return attr.value.stringValue || attr.value.intValue || attr.value;
            }
        }
    }
    // Handle object format
    else if (typeof attributes === 'object') {
        for (const key of keys) {
            if (attributes[key] !== undefined) {
                return attributes[key];
            }
        }
    }
    
    return null;
}

/** Creates modal dialog overlay with title, content, and buttons with handlers */
export function createModal(title, contentHtml, buttons = []) {
    const modal = document.createElement('div');
    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;';
    
    const buttonsHtml = buttons.map(btn => 
        renderActionButton(btn.id, btn.label, btn.style || 'secondary')
    ).join('');
    
    modal.innerHTML = `
        <div style="background: var(--bg-card); border-radius: 8px; padding: 24px; max-width: 600px; max-height: 80vh; overflow: auto; box-shadow: var(--shadow);">
            <h3 style="margin: 0 0 16px 0; font-size: 16px;">${title}</h3>
            <div style="margin-bottom: 20px;">
                ${contentHtml}
            </div>
            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                ${buttonsHtml}
            </div>
        </div>
    `;
    
    // Attach button handlers
    buttons.forEach(btn => {
        const buttonEl = modal.querySelector(`#${btn.id}`);
        if (buttonEl && btn.handler) {
            buttonEl.onclick = () => btn.handler(modal);
        }
    });
    
    // Close on background click
    modal.onclick = (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    };
    
    document.body.appendChild(modal);
    return modal;
}

/** Closes and removes modal from DOM */
export function closeModal(modal) {
    if (modal && modal.parentNode) {
        document.body.removeChild(modal);
    }
}

/** Extracts service.name from OTEL entity (span/trace/log) resource or attributes */
export function extractServiceName(entity) {
    if (!entity) return null;
    
    // Direct properties
    if (entity.service_name) return entity.service_name;
    if (entity.serviceName) return entity.serviceName;
    
    // Check resource attributes (OTEL format)
    if (entity.resource && entity.resource['service.name']) {
        return entity.resource['service.name'];
    }
    
    // Check attributes
    return getAttributeValue(entity, ['service.name']);
}

/** Switches to tab, sets filter input value, and triggers filter function after delay */
export function navigateToTabWithFilter(tabName, inputId, filterValue, filterFnName, delay = 300) {
    if (window.switchTab) {
        window.switchTab(tabName);
    }
    
    setTimeout(() => {
        const input = document.getElementById(inputId);
        if (input) {
            input.value = filterValue;
            // Trigger the filter function
            if (window[filterFnName]) {
                window[filterFnName]();
            }
        }
    }, delay);
}

/** Copies JSON data to clipboard and shows temporary feedback message */
export function copyJsonWithFeedback(data, feedbackElementId) {
    const feedback = document.getElementById(feedbackElementId);
    copyToClipboard(JSON.stringify(data, null, 2), feedback);
}

/** Downloads telemetry JSON with consistent filename format (type-id.json) */
export function downloadTelemetryJson(data, type, id) {
    const filename = `${type}-${id}.json`;
    downloadJson(data, filename);
}

/** Smoothly scrolls element into view with configurable alignment */
export function smoothScrollTo(element, block = 'nearest') {
    if (element) {
        element.scrollIntoView({ behavior: 'smooth', block });
    }
}

/** Returns sort indicator arrow (↑/↓) for table headers based on current sort state */
export function getSortIndicator(column, currentSort) {
    if (!currentSort || currentSort.column !== column) return '⇅';
    return currentSort.direction === 'asc' ? '↑' : '↓';
}

/** Destroys Chart.js instance and removes from tracking map */
export function destroyChart(chartId, chartInstancesMap) {
    if (chartInstancesMap && chartInstancesMap[chartId]) {
        chartInstancesMap[chartId].destroy();
        delete chartInstancesMap[chartId];
    }
}


/** Closes all expanded UI items (views/modals/details) based on config selectors and callbacks */
export function closeAllExpandedItems(config) {
    
    if (config.containers) {
        config.containers.forEach(selector => {
            const elements = document.querySelectorAll(selector);
            elements.forEach(el => {
                if (el.remove) el.remove();
                else {
                    el.style.display = 'none';
                    el.innerHTML = '';
                }
            });
        });
    }
    
    if (config.classes) {
        config.classes.forEach(item => {
            document.querySelectorAll(item.selector).forEach(el => {
                if (item.class) {
                    el.classList.remove(item.class);
                }
                if (item.style) {
                    for (const [prop, value] of Object.entries(item.style)) {
                        el.style[prop] = value;
                    }
                }
            });
        });
    }
    
    if (config.callbacks) {
        config.callbacks.forEach(fn => {
            if (typeof fn === 'function') fn();
        });
    }
}
