/**
 * WebSocket client for real-time updates in HiberNet Enhanced
 * Handles real-time proxy updates, statistics, and system notifications
 */

// WebSocket connection management
window.HiberProxyWS = {
    socket: null,
    connected: false,
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,
    reconnectDelay: 1000
};

// Initialize WebSocket connection when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeWebSocket();
});

function initializeWebSocket() {
    console.log('[WebSocket] Initializing connection...');
    
    try {
        // Initialize Socket.IO connection
        window.HiberProxyWS.socket = io();
        
        // Setup event handlers
        setupWebSocketHandlers();
        
    } catch (error) {
        console.error('[WebSocket] Failed to initialize:', error);
        updateConnectionStatus(false);
    }
}

function setupWebSocketHandlers() {
    const socket = window.HiberProxyWS.socket;
    
    // Connection events
    socket.on('connect', function() {
        console.log('[WebSocket] Connected to server');
        window.HiberProxyWS.connected = true;
        window.HiberProxyWS.reconnectAttempts = 0;
        updateConnectionStatus(true);
        
        // Request initial stats
        socket.emit('get_stats');
    });
    
    socket.on('disconnect', function() {
        console.log('[WebSocket] Disconnected from server');
        window.HiberProxyWS.connected = false;
        updateConnectionStatus(false);
        
        // Attempt to reconnect
        attemptReconnect();
    });
    
    socket.on('connect_error', function(error) {
        console.error('[WebSocket] Connection error:', error);
        window.HiberProxyWS.connected = false;
        updateConnectionStatus(false);
        
        // Attempt to reconnect
        attemptReconnect();
    });
    
    // Data update events
    socket.on('stats_update', function(data) {
        console.log('[WebSocket] Received stats update:', data);
        window.HiberProxy.stats = data;
        updateStatsDisplay(data);
        updateProxyCount();
    });
    
    socket.on('proxy_update', function(data) {
        console.log('[WebSocket] Received proxy update:', data);
        handleProxyUpdate(data);
    });
    
    socket.on('status', function(data) {
        console.log('[WebSocket] Status message:', data.message);
        if (window.showNotification) {
            window.showNotification(data.message, 'info');
        }
    });
    
    socket.on('error', function(data) {
        console.error('[WebSocket] Server error:', data.message);
        if (window.showNotification) {
            window.showNotification('Server error: ' + data.message, 'error');
        }
    });
    
    // System events
    socket.on('system_notification', function(data) {
        console.log('[WebSocket] System notification:', data);
        if (window.showNotification) {
            window.showNotification(data.message, data.type || 'info');
        }
    });

    // Activity updates for Recent Activity section
    socket.on('activity_update', function(data) {
        console.log('[WebSocket] Activity update:', data);
        if (window.addActivity) {
            window.addActivity(data.message);
        }
    });
}

function attemptReconnect() {
    if (window.HiberProxyWS.reconnectAttempts >= window.HiberProxyWS.maxReconnectAttempts) {
        console.error('[WebSocket] Max reconnection attempts reached');
        if (window.showNotification) {
            window.showNotification('Connection lost. Please refresh the page.', 'error');
        }
        return;
    }
    
    window.HiberProxyWS.reconnectAttempts++;
    const delay = window.HiberProxyWS.reconnectDelay * Math.pow(2, window.HiberProxyWS.reconnectAttempts - 1);
    
    console.log(`[WebSocket] Attempting to reconnect in ${delay}ms (attempt ${window.HiberProxyWS.reconnectAttempts})`);
    
    setTimeout(() => {
        if (!window.HiberProxyWS.connected) {
            console.log('[WebSocket] Reconnecting...');
            window.HiberProxyWS.socket.connect();
        }
    }, delay);
}

function handleProxyUpdate(data) {
    const { type, data: updateData } = data;
    
    switch (type) {
        case 'download':
            handleDownloadUpdate(updateData);
            break;
        case 'check':
            handleCheckUpdate(updateData);
            break;
        case 'add':
            handleAddUpdate(updateData);
            break;
        case 'cleanup':
            handleCleanupUpdate(updateData);
            break;
        default:
            console.log('[WebSocket] Unknown proxy update type:', type);
    }
    
    // Refresh stats after any proxy update
    if (window.loadStats) {
        window.loadStats();
    }
    
    // Update protocol chart if it exists
    if (window.updateProtocolChart) {
        window.updateProtocolChart();
    }
}

function handleDownloadUpdate(data) {
    const message = `Downloaded ${data.total_proxies_imported || 0} new proxies from ${data.successful_sources || 0} sources`;
    
    if (window.addActivity) {
        window.addActivity(message);
    }
    
    if (window.showNotification) {
        window.showNotification(message, 'success');
    }
    
    // Update system status
    updateSystemStatus('Download completed');
}

function handleCheckUpdate(data) {
    const message = `Checked ${data.checked || 0} proxies, ${data.working || 0} working (${((data.working || 0) / (data.checked || 1) * 100).toFixed(1)}% success rate)`;
    
    if (window.addActivity) {
        window.addActivity(message);
    }
    
    if (window.showNotification) {
        window.showNotification(message, 'success');
    }
    
    // Update system status
    updateSystemStatus('Check completed');
}

function handleAddUpdate(data) {
    const message = `Added proxy: ${data.proxy} (ID: ${data.proxy_id})`;
    
    if (window.addActivity) {
        window.addActivity(message);
    }
    
    // Update system status
    updateSystemStatus('Proxy added');
}

function handleCleanupUpdate(data) {
    const message = `Cleaned up ${data.removed || 0} failed proxies`;
    
    if (window.addActivity) {
        window.addActivity(message);
    }
    
    if (window.showNotification) {
        window.showNotification(message, 'success');
    }
    
    // Update system status
    updateSystemStatus('Cleanup completed');
}

function updateSystemStatus(status) {
    const systemStatusElement = document.getElementById('system-status');
    if (systemStatusElement) {
        systemStatusElement.textContent = status;
        
        // Reset to "System OK" after 5 seconds
        setTimeout(() => {
            if (systemStatusElement.textContent === status) {
                systemStatusElement.textContent = 'System OK';
            }
        }, 5000);
    }
}

// Utility functions for WebSocket communication
function requestStatsUpdate() {
    if (window.HiberProxyWS.connected && window.HiberProxyWS.socket) {
        window.HiberProxyWS.socket.emit('get_stats');
    }
}

function sendCommand(command, data = {}) {
    if (window.HiberProxyWS.connected && window.HiberProxyWS.socket) {
        window.HiberProxyWS.socket.emit(command, data);
    } else {
        console.warn('[WebSocket] Cannot send command - not connected');
        if (window.showNotification) {
            window.showNotification('Not connected to server', 'warning');
        }
    }
}

// Export functions for global access
window.requestStatsUpdate = requestStatsUpdate;
window.sendCommand = sendCommand;

// Periodic stats updates via WebSocket
setInterval(() => {
    if (window.HiberProxyWS.connected) {
        requestStatsUpdate();
    }
}, 30000); // Every 30 seconds
