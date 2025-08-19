/**
 * Main JavaScript functionality for HiberNet Enhanced Web Interface
 * Provides terminal-style interactions and real-time updates
 */

// Global application state
window.HiberProxy = {
    connected: false,
    stats: {},
    proxies: [],
    config: {}
};

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    console.log('[HiberProxy] Initializing web interface...');
    
    // Initialize components
    initializeTerminalEffects();
    updateConnectionStatus(true);
    
    // Load initial data
    loadInitialData();
    
    // Setup periodic updates
    setupPeriodicUpdates();
    
    console.log('[HiberProxy] Web interface initialized');
}

function initializeTerminalEffects() {
    // Add terminal-style cursor blinking effect to active elements
    const activeElements = document.querySelectorAll('.terminal-cursor');
    activeElements.forEach(element => {
        element.style.animation = 'blink 1s infinite';
    });
    
    // Add CSS for blinking cursor if not already present
    if (!document.getElementById('terminal-effects-css')) {
        const style = document.createElement('style');
        style.id = 'terminal-effects-css';
        style.textContent = `
            @keyframes blink {
                0%, 50% { opacity: 1; }
                51%, 100% { opacity: 0; }
            }
            .terminal-cursor::after {
                content: '_';
                animation: blink 1s infinite;
                color: var(--orange-primary);
            }
        `;
        document.head.appendChild(style);
    }
}

function updateConnectionStatus(connected) {
    window.HiberProxy.connected = connected;
    
    const statusIndicator = document.getElementById('connection-status');
    const statusText = document.querySelector('.status-text');
    
    if (statusIndicator && statusText) {
        if (connected) {
            statusIndicator.style.color = 'var(--success-color)';
            statusText.textContent = 'Connected';
        } else {
            statusIndicator.style.color = 'var(--error-color)';
            statusText.textContent = 'Disconnected';
        }
    }
}

function loadInitialData() {
    // Load system statistics
    loadStats();
    
    // Update proxy count in footer
    updateProxyCount();
}

function loadStats() {
    fetch('/api/stats')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            window.HiberProxy.stats = data;
            updateStatsDisplay(data);
        })
        .catch(error => {
            console.error('[HiberProxy] Error loading stats:', error);
            showNotification('Error loading statistics: ' + error.message, 'error');
        });
}

function updateStatsDisplay(stats) {
    // Update dashboard stats if elements exist
    const elements = {
        'total-proxies': stats.total_proxies,
        'working-proxies': stats.working_proxies,
        'failed-proxies': stats.total_proxies - stats.working_proxies,
        'success-rate': stats.average_success_rate ? stats.average_success_rate.toFixed(1) + '%' : 'N/A',
        'avg-response-time': stats.average_response_time ? stats.average_response_time.toFixed(0) + 'ms' : 'N/A',
        'last-check': stats.last_check || 'Never'
    };
    
    Object.entries(elements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    });
}

function updateProxyCount() {
    const proxyCountElement = document.getElementById('proxy-count');
    if (proxyCountElement && window.HiberProxy.stats.total_proxies !== undefined) {
        proxyCountElement.textContent = `${window.HiberProxy.stats.total_proxies} proxies`;
    }
}

function setupPeriodicUpdates() {
    // Update stats every 30 seconds
    setInterval(() => {
        if (window.HiberProxy.connected) {
            loadStats();
        }
    }, 30000);
    
    // Update timestamp every second
    setInterval(updateTimestamp, 1000);
}

function updateTimestamp() {
    const timestampElement = document.getElementById('last-update');
    if (timestampElement) {
        timestampElement.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
    }
}

// Utility functions for API calls
function apiCall(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    const finalOptions = { ...defaultOptions, ...options };
    
    return fetch(endpoint, finalOptions)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        });
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Style the notification
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background-color: var(--bg-secondary);
        color: var(--text-primary);
        border: 2px solid var(--orange-primary);
        border-radius: var(--border-radius);
        padding: 1rem;
        font-family: var(--font-mono);
        font-size: var(--font-size-base);
        z-index: 1000;
        max-width: 300px;
        word-wrap: break-word;
        animation: slideIn 0.3s ease;
    `;
    
    // Add type-specific styling
    if (type === 'error') {
        notification.style.borderColor = 'var(--error-color)';
    } else if (type === 'success') {
        notification.style.borderColor = 'var(--success-color)';
    } else if (type === 'warning') {
        notification.style.borderColor = 'var(--warning-color)';
    }
    
    // Add slide-in animation if not already present
    if (!document.getElementById('notification-css')) {
        const style = document.createElement('style');
        style.id = 'notification-css';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 5000);
    
    // Allow manual close on click
    notification.addEventListener('click', () => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    });
}

// Terminal-style command execution
function executeCommand(command, args = []) {
    console.log(`[HiberProxy] Executing command: ${command}`, args);
    
    switch (command) {
        case 'download':
            return downloadProxies(args[0]);
        case 'check':
            return checkProxies(args[0]);
        case 'cleanup':
            return cleanupDatabase();
        case 'export':
            return exportProxies(args[0]);
        case 'add':
            return addProxy(args[0]);
        default:
            throw new Error(`Unknown command: ${command}`);
    }
}

// Command implementations
function downloadProxies(protocol = null) {
    showNotification('Starting proxy download...', 'info');

    return apiCall('/api/download', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ protocol })
    })
    .then(data => {
        showNotification(`Downloaded ${data.total_proxies_imported || 0} new proxies`, 'success');
        loadStats();
        return data;
    })
    .catch(error => {
        showNotification('Error downloading proxies: ' + error.message, 'error');
        throw error;
    });
}

function checkProxies(protocol = null) {
    showNotification('Starting proxy check...', 'info');

    return apiCall('/api/check', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ protocol, limit: 100 })
    })
    .then(data => {
        showNotification(`Checked ${data.checked || 0} proxies, ${data.working || 0} working`, 'success');
        loadStats();
        return data;
    })
    .catch(error => {
        showNotification('Error checking proxies: ' + error.message, 'error');
        throw error;
    });
}

function cleanupDatabase() {
    if (!confirm('Are you sure you want to cleanup failed proxies?')) {
        return Promise.resolve(null);
    }

    showNotification('Starting database cleanup...', 'info');

    return apiCall('/api/cleanup', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(data => {
        showNotification(`Cleaned up ${data.removed || 0} failed proxies`, 'success');
        loadStats();
        return data;
    })
    .catch(error => {
        showNotification('Error during cleanup: ' + error.message, 'error');
        throw error;
    });
}

function exportProxies(format = 'txt') {
    showNotification('Exporting proxies...', 'info');
    window.location.href = `/api/export?format=${format}`;
}

function addProxy(proxyString) {
    if (!proxyString) {
        proxyString = prompt('Enter proxy (host:port or protocol://host:port):');
        if (!proxyString) return Promise.resolve(null);
    }

    return apiCall('/api/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ proxy: proxyString })
    })
    .then(data => {
        showNotification(`Proxy added successfully (ID: ${data.proxy_id})`, 'success');
        loadStats();
        return data;
    })
    .catch(error => {
        showNotification('Error adding proxy: ' + error.message, 'error');
        throw error;
    });
}

// Export functions for global access
window.downloadProxies = downloadProxies;
window.checkProxies = checkProxies;
window.cleanupDatabase = cleanupDatabase;
window.exportProxies = exportProxies;
window.addProxy = addProxy;
window.executeCommand = executeCommand;
window.showNotification = showNotification;
