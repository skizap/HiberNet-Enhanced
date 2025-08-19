#!/usr/bin/env python3
"""
Simple startup script for HiberNet Enhanced Web Interface
Provides clean startup with minimal output and proper error handling
"""

import sys
import os
from pathlib import Path

# Add hiber_proxy to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    """Start the web interface with clean output"""
    try:
        print("🚀 Starting HiberNet Enhanced Web Interface...")
        print("⏳ Initializing application components...")
        
        # Import here to catch any import errors
        from hiber_proxy.web.app import create_app
        
        # Create the app
        app, socketio = create_app()
        
        print("✅ Application initialized successfully!")
        print("🌐 Server starting at: http://localhost:5000")
        print("📱 Open your browser and navigate to the URL above")
        print("🔄 The dashboard may take a few moments to load proxy data")
        print("-" * 60)
        
        # Start the server with clean configuration
        socketio.run(
            app,
            debug=False,
            host='127.0.0.1',  # localhost only
            port=5000,
            use_reloader=False,
            log_output=False
        )
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down HiberNet Enhanced...")
        sys.exit(0)
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("💡 Make sure you're running from the virtual environment:")
        print("   source hiber_venv/bin/activate")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start web interface: {e}")
        print("💡 Check the logs for more details")
        sys.exit(1)

if __name__ == '__main__':
    main()
