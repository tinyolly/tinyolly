/**
 * Collector Module - Manages OTel Collector configuration via OpAMP
 */

// Templates loaded from API
let availableTemplates = [];
let currentConfig = '';

/**
 * Initialize the collector tab
 */
export async function initCollector() {
    const editor = document.getElementById('collector-config-editor');
    if (editor) {
        // Add tab key support for indentation
        editor.addEventListener('keydown', handleEditorKeydown);

        // Add real-time validation
        editor.addEventListener('input', debounce(() => validateConfig(), 500));
    }

    // Load templates from API
    await loadTemplates();

    // Load current config from OpAMP server
    await loadCollectorConfig();
}

/**
 * Load templates from API and render template cards
 */
async function loadTemplates() {
    const templatesGrid = document.querySelector('.templates-grid');
    if (!templatesGrid) return;

    try {
        const response = await fetch('/api/opamp/templates');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        availableTemplates = data.templates || [];

        if (availableTemplates.length === 0) {
            templatesGrid.innerHTML = '<div class="empty-state">No templates available</div>';
            return;
        }

        // Render template cards
        templatesGrid.innerHTML = availableTemplates.map(template => `
            <div class="template-card" onclick="loadTemplate('${template.id}')">
                <h4>${escapeHtml(template.name)}</h4>
                <p>${escapeHtml(template.description)}</p>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error loading templates:', error);
        templatesGrid.innerHTML = '<div class="empty-state">Failed to load templates</div>';
    }
}

/**
 * Handle keydown events in the editor for tab support
 */
function handleEditorKeydown(e) {
    if (e.key === 'Tab') {
        e.preventDefault();
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '  ' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 2;
    }
}

/**
 * Debounce helper function
 */
function debounce(func, wait) {
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

/**
 * Load OpAMP status and connected agents
 */
export async function loadOpampStatus() {
    const statusContainer = document.getElementById('opamp-status-container');
    const agentsContainer = document.getElementById('agents-container');

    if (!statusContainer) return;

    try {
        const response = await fetch('/api/opamp/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // Render status
        statusContainer.innerHTML = `
            <div class="status-item">
                <span class="status-label">Server Status</span>
                <span class="status-value connected">${data.status || 'OK'}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Connected Agents</span>
                <span class="status-value">${data.agent_count || 0}</span>
            </div>
        `;

        // Render agents
        if (data.agents && Object.keys(data.agents).length > 0) {
            agentsContainer.innerHTML = Object.entries(data.agents).map(([id, agent]) => `
                <div class="agent-card">
                    <div class="agent-card-header">
                        <span class="agent-status ${agent.status}">${agent.status}</span>
                    </div>
                    <div class="agent-id">${id}</div>
                    <div class="agent-info">
                        <span class="agent-info-label">Type:</span>
                        <span class="agent-info-value">${agent.agent_type || 'OTel Collector'}</span>
                        <span class="agent-info-label">Version:</span>
                        <span class="agent-info-value">${agent.agent_version || 'Unknown'}</span>
                        <span class="agent-info-label">Last Seen:</span>
                        <span class="agent-info-value">${formatTimestamp(agent.last_seen)}</span>
                    </div>
                </div>
            `).join('');
        } else {
            agentsContainer.innerHTML = '<div class="empty-state">No collectors connected. Make sure the OTel Collector is running with OpAMP extension enabled.</div>';
        }

    } catch (error) {
        console.error('Error loading OpAMP status:', error);
        statusContainer.innerHTML = `
            <div class="status-item">
                <span class="status-label">Server Status</span>
                <span class="status-value disconnected">Unavailable</span>
            </div>
        `;
        agentsContainer.innerHTML = '<div class="empty-state">Unable to connect to OpAMP server</div>';
    }
}

/**
 * Format timestamp for display
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch {
        return timestamp;
    }
}

/**
 * Refresh OpAMP status (called by button click)
 */
export async function refreshOpampStatus() {
    await loadOpampStatus();
}

/**
 * Load current collector config from OpAMP server
 */
export async function loadCollectorConfig() {
    const editor = document.getElementById('collector-config-editor');
    const statusEl = document.getElementById('config-status');

    if (!editor) return;

    setConfigStatus('pending', 'Loading...');

    try {
        const response = await fetch('/api/opamp/config');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.config) {
            editor.value = data.config;
            currentConfig = data.config;
            setConfigStatus('success', 'Loaded');
            setTimeout(() => setConfigStatus(''), 2000);
        } else if (data.status === 'no_agents_connected') {
            setConfigStatus('pending', 'No agents connected - showing default');
            // Keep current editor content
        } else {
            setConfigStatus('error', 'No config available');
        }

        await validateConfig();

    } catch (error) {
        console.error('Error loading config:', error);
        setConfigStatus('error', 'Failed to load');
    }
}

/**
 * Reset config editor to default
 */
export async function resetConfigToDefault() {
    // Load the 'default' template
    await loadTemplate('default');
    setConfigStatus('success', 'Reset to default');
    setTimeout(() => setConfigStatus(''), 2000);
}

// Store pending config for diff confirmation
let pendingConfig = null;

/**
 * Compute diff between two config strings
 */
function computeDiff(oldConfig, newConfig) {
    const oldLines = oldConfig.split('\n');
    const newLines = newConfig.split('\n');
    
    // Simple line-by-line diff algorithm
    const diff = [];
    let oldIndex = 0;
    let newIndex = 0;
    
    while (oldIndex < oldLines.length || newIndex < newLines.length) {
        if (oldIndex >= oldLines.length) {
            // Only new lines left
            diff.push({ type: 'added', line: newLines[newIndex] });
            newIndex++;
        } else if (newIndex >= newLines.length) {
            // Only old lines left
            diff.push({ type: 'removed', line: oldLines[oldIndex] });
            oldIndex++;
        } else if (oldLines[oldIndex] === newLines[newIndex]) {
            // Lines match
            diff.push({ type: 'context', line: oldLines[oldIndex] });
            oldIndex++;
            newIndex++;
        } else {
            // Lines differ - check if it's an addition or deletion
            // Look ahead to find matching line
            let foundMatch = false;
            for (let lookAhead = 1; lookAhead <= 5 && newIndex + lookAhead < newLines.length; lookAhead++) {
                if (oldLines[oldIndex] === newLines[newIndex + lookAhead]) {
                    // Found match ahead - these are additions
                    for (let i = 0; i < lookAhead; i++) {
                        diff.push({ type: 'added', line: newLines[newIndex + i] });
                    }
                    newIndex += lookAhead;
                    foundMatch = true;
                    break;
                }
            }
            
            if (!foundMatch) {
                // Check if old line appears later in new config
                let foundOld = false;
                for (let lookAhead = 1; lookAhead <= 5 && oldIndex + lookAhead < oldLines.length; lookAhead++) {
                    if (newLines[newIndex] === oldLines[oldIndex + lookAhead]) {
                        // Found match ahead - these are deletions
                        for (let i = 0; i < lookAhead; i++) {
                            diff.push({ type: 'removed', line: oldLines[oldIndex + i] });
                        }
                        oldIndex += lookAhead;
                        foundOld = true;
                        break;
                    }
                }
                
                if (!foundOld) {
                    // Lines are different - mark as removed and added
                    diff.push({ type: 'removed', line: oldLines[oldIndex] });
                    diff.push({ type: 'added', line: newLines[newIndex] });
                    oldIndex++;
                    newIndex++;
                }
            }
        }
    }
    
    return diff;
}

/**
 * Render diff in the modal
 */
function renderDiff(diff) {
    const diffContent = document.getElementById('config-diff-content');
    if (!diffContent) return;
    
    if (diff.length === 0 || diff.every(d => d.type === 'context')) {
        diffContent.innerHTML = '<div class="diff-no-changes">No changes detected</div>';
        return;
    }
    
    let html = '';
    let hasChanges = false;
    
    for (const item of diff) {
        if (item.type === 'context') {
            html += `<div class="diff-line context">${escapeHtml(item.line)}</div>`;
        } else {
            hasChanges = true;
            html += `<div class="diff-line ${item.type}">${escapeHtml(item.line)}</div>`;
        }
    }
    
    if (!hasChanges) {
        diffContent.innerHTML = '<div class="diff-no-changes">No changes detected</div>';
    } else {
        diffContent.innerHTML = html;
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Show config diff modal
 */
export async function showConfigDiff() {
    const editor = document.getElementById('collector-config-editor');
    if (!editor) return;
    
    const newConfig = editor.value;
    
    // Validate first
    const isValid = await validateConfig();
    if (!isValid) {
        setConfigStatus('error', 'Invalid YAML');
        return;
    }
    
    // Get current config if not already loaded
    if (!currentConfig) {
        try {
            const response = await fetch('/api/opamp/config');
            if (response.ok) {
                const data = await response.json();
                if (data.config) {
                    currentConfig = data.config;
                }
            }
        } catch (error) {
            console.error('Error loading current config:', error);
        }
    }
    
    // If still no current config, use empty string
    const oldConfig = currentConfig || '';
    
    // Compute and render diff
    const diff = computeDiff(oldConfig, newConfig);
    renderDiff(diff);
    
    // Store pending config
    pendingConfig = newConfig;
    
    // Show modal
    const modal = document.getElementById('config-diff-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

/**
 * Close config diff modal
 */
export function closeConfigDiff() {
    const modal = document.getElementById('config-diff-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    pendingConfig = null;
}

/**
 * Confirm and apply config after showing diff
 */
export async function confirmApplyConfig() {
    if (!pendingConfig) {
        closeConfigDiff();
        return;
    }
    
    closeConfigDiff();
    
    // Apply the pending config
    const editor = document.getElementById('collector-config-editor');
    if (editor) {
        editor.value = pendingConfig;
    }
    
    // Now apply it
    await applyCollectorConfigDirect(pendingConfig);
    pendingConfig = null;
}

/**
 * Apply the current config via OpAMP (internal function)
 */
async function applyCollectorConfigDirect(config) {
    setConfigStatus('pending', 'Applying...');

    try {
        const response = await fetch('/api/opamp/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ config })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();

        setConfigStatus('success', `Applied to ${data.affected_instance_ids?.length || 0} agent(s)`);
        currentConfig = config;

        // Refresh status after a short delay
        setTimeout(() => {
            loadOpampStatus();
            setConfigStatus('');
        }, 3000);

    } catch (error) {
        console.error('Error applying config:', error);
        setConfigStatus('error', `Failed: ${error.message}`);
    }
}

/**
 * Apply the current config via OpAMP (public function - shows diff first)
 */
export async function applyCollectorConfig() {
    const editor = document.getElementById('collector-config-editor');
    if (!editor) return;

    const config = editor.value;

    // Validate first
    const isValid = await validateConfig();
    if (!isValid) {
        setConfigStatus('error', 'Invalid YAML');
        return;
    }
    
    // Show diff first, then user can confirm
    await showConfigDiff();
}

/**
 * Set config status indicator
 */
function setConfigStatus(type, message) {
    const statusEl = document.getElementById('config-status');
    if (!statusEl) return;

    statusEl.className = 'config-status';
    if (type) {
        statusEl.className = `config-status ${type}`;
        statusEl.textContent = message;
    }
}

/**
 * Validate YAML config (enhanced validation with YAML parsing)
 */
export async function validateConfig() {
    const editor = document.getElementById('collector-config-editor');
    const validationEl = document.getElementById('config-validation');

    if (!editor || !validationEl) return false;

    const config = editor.value;

    // Basic structure checks first
    try {
        const lines = config.split('\n');
        let hasService = false;
        let hasReceivers = false;
        let hasExporters = false;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const trimmed = line.trim();

            // Skip empty lines and comments
            if (!trimmed || trimmed.startsWith('#')) continue;

            // Check for required sections
            if (trimmed.startsWith('service:')) hasService = true;
            if (trimmed.startsWith('receivers:')) hasReceivers = true;
            if (trimmed.startsWith('exporters:')) hasExporters = true;

            // Check for invalid characters in keys
            if (trimmed.includes('\t')) {
                validationEl.className = 'config-validation invalid';
                validationEl.textContent = `Line ${i + 1}: Tab characters not allowed in YAML, use spaces`;
                return false;
            }
        }

        // Check for required sections
        const missing = [];
        if (!hasReceivers) missing.push('receivers');
        if (!hasExporters) missing.push('exporters');
        if (!hasService) missing.push('service');

        if (missing.length > 0) {
            validationEl.className = 'config-validation invalid';
            validationEl.textContent = `Missing required sections: ${missing.join(', ')}`;
            return false;
        }

        // Try to parse YAML - this will catch syntax errors
        try {
            // Use server-side validation for more thorough checking
            const response = await fetch('/api/opamp/validate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ config })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.valid) {
                    validationEl.className = 'config-validation valid';
                    validationEl.textContent = 'Configuration is valid';
                    return true;
                } else {
                    validationEl.className = 'config-validation invalid';
                    validationEl.textContent = result.error || 'Configuration has errors';
                    return false;
                }
            } else {
                // Fallback to basic validation if server validation fails
                const error = await response.json().catch(() => ({ detail: 'Validation failed' }));
                validationEl.className = 'config-validation invalid';
                validationEl.textContent = error.detail || 'Validation error';
                return false;
            }
        } catch (fetchError) {
            // If server validation is unavailable, do basic YAML parsing check
            // Try to use js-yaml if available, otherwise just mark as "needs server validation"
            if (typeof window.jsyaml !== 'undefined') {
                try {
                    window.jsyaml.load(config);
                    validationEl.className = 'config-validation valid';
                    validationEl.textContent = 'Configuration syntax is valid (full validation requires server)';
                    return true;
                } catch (yamlError) {
                    validationEl.className = 'config-validation invalid';
                    validationEl.textContent = `YAML syntax error: ${yamlError.message}`;
                    return false;
                }
            } else {
                // No YAML parser available - just check structure
                validationEl.className = 'config-validation warning';
                validationEl.textContent = 'Basic structure OK (full validation requires server)';
                return true; // Allow it through, server will catch errors
            }
        }

    } catch (error) {
        validationEl.className = 'config-validation invalid';
        validationEl.textContent = `Validation error: ${error.message}`;
        return false;
    }
}

/**
 * Load a config template from API
 */
export async function loadTemplate(templateId) {
    const editor = document.getElementById('collector-config-editor');
    if (!editor) return;

    setConfigStatus('pending', 'Loading template...');

    try {
        const response = await fetch(`/api/opamp/templates/${templateId}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        if (data.config) {
            editor.value = data.config;
            await validateConfig();
            setConfigStatus('success', `Loaded "${templateId}" template`);
            setTimeout(() => setConfigStatus(''), 2000);
        } else {
            setConfigStatus('error', 'Template has no config');
        }
    } catch (error) {
        console.error('Error loading template:', error);
        setConfigStatus('error', `Failed to load template: ${error.message}`);
    }
}

// Export functions to window for HTML onclick handlers
window.refreshOpampStatus = refreshOpampStatus;
window.loadCollectorConfig = loadCollectorConfig;
window.resetConfigToDefault = resetConfigToDefault;
window.applyCollectorConfig = applyCollectorConfig;
window.showConfigDiff = showConfigDiff;
window.closeConfigDiff = closeConfigDiff;
window.confirmApplyConfig = confirmApplyConfig;
window.loadTemplate = loadTemplate;
