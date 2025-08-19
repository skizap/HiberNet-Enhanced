"""
Flask web application for HiberNet Enhanced

Provides web interface with dark orange terminal aesthetic for proxy management,
configuration, and analytics with real-time updates via WebSocket.
"""

import os
import sys
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hiber_proxy.main import HiberProxyApp
from hiber_proxy.core.logging_config import setup_logging, get_logger
from .api.routes import api_bp

def create_app(config_path=None):
    """Create and configure Flask application"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'hiber-proxy-enhanced-secret-key'

    # Enable CORS for API endpoints
    CORS(app)

    # Initialize SocketIO with reduced logging
    socketio = SocketIO(app, cors_allowed_origins="*", logger=False, engineio_logger=False)

    # Setup logging first
    logger = get_logger('web')
    logger.info("Initializing HiberNet Enhanced web interface...")

    try:
        # Initialize HiberProxy app with error handling
        hiber_app = HiberProxyApp(config_path)
        logger.info("HiberProxy app initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize HiberProxy app: {e}")
        # Create a minimal app for debugging
        hiber_app = None

    # Store app instances for access in routes
    app.hiber_app = hiber_app
    app.socketio = socketio
    app.logger_instance = logger

    # Register routes
    register_routes(app)
    app.register_blueprint(api_bp)
    if hiber_app:
        register_socketio_events(socketio, hiber_app, logger)

    logger.info("Web interface setup completed")
    return app, socketio

def register_routes(app):
    """Register main web routes"""

    @app.route('/')
    def index():
        """Main dashboard"""
        try:
            return render_template('index.html')
        except Exception as e:
            app.logger_instance.error(f"Error rendering index: {e}")
            return f"Error loading dashboard: {e}", 500

    @app.route('/proxies')
    def proxies():
        """Proxy management page"""
        return render_template('proxies.html')

    @app.route('/config')
    def config():
        """Configuration page"""
        return render_template('config.html')

    @app.route('/analytics')
    def analytics():
        """Analytics dashboard"""
        return render_template('analytics.html')

    @app.route('/stress-test')
    def stress_test():
        """Network stress testing page"""
        return render_template('stress_test.html')

def register_socketio_events(socketio, hiber_app, logger):
    """Register SocketIO events for real-time updates"""
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        logger.info("Client connected to WebSocket")
        # Don't emit status message to avoid annoying notifications on tab changes
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info("Client disconnected from WebSocket")
    
    @socketio.on('get_stats')
    def handle_get_stats():
        """Handle real-time stats request"""
        try:
            stats = hiber_app.get_statistics()
            emit('stats_update', stats)
        except Exception as e:
            logger.error(f"Error getting stats for WebSocket: {e}")
            emit('error', {'message': str(e)})

if __name__ == '__main__':
    print("🚀 Starting HiberNet Enhanced Web Interface...")
    app, socketio = create_app()
    print("✅ Application initialized successfully!")
    print("🌐 Server running at: http://localhost:5000")
    print("📱 Open your browser and navigate to the URL above")
    print("-" * 50)

    # Run with minimal logging and only show localhost
    socketio.run(
        app,
        debug=False,  # Disable debug mode to reduce output
        host='127.0.0.1',  # Use localhost instead of 0.0.0.0
        port=5000,
        use_reloader=False,  # Disable auto-reloader
        log_output=False  # Minimize Flask output
    )
