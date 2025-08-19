#!/usr/bin/env python3
"""
Web server launcher for HiberProxy Enhanced

Starts the Flask web interface with proper configuration and error handling.
Automatically detects and uses virtual environment if available.
"""

import sys
import os
from pathlib import Path

def check_virtual_environment():
    """Check if we're running in a virtual environment and suggest activation if not"""
    # Check if we're in a virtual environment
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)

    if not in_venv:
        # Check if virtual environment exists
        project_root = Path(__file__).parent.parent.parent
        venv_paths = [
            project_root / "hiber_venv",
            project_root / "venv",
            project_root / ".venv"
        ]

        existing_venv = None
        for venv_path in venv_paths:
            if venv_path.exists():
                existing_venv = venv_path
                break

        if existing_venv:
            print("⚠️  Warning: Virtual environment detected but not activated!")
            print(f"   Virtual environment found at: {existing_venv}")
            print()
            print("To activate the virtual environment:")
            if os.name == 'nt':  # Windows
                print(f"   {existing_venv}\\Scripts\\activate.bat")
                print("   OR run: activate_hiber_env.bat")
            else:  # Unix/Linux/macOS
                print(f"   source {existing_venv}/bin/activate")
                print("   OR run: source activate_hiber_env.sh")
            print()
            print("Then run this script again.")
            print()

            # Ask if user wants to continue anyway
            try:
                response = input("Continue without virtual environment? [y/N]: ").strip().lower()
                if response not in ['y', 'yes']:
                    print("Exiting. Please activate the virtual environment first.")
                    return False
            except KeyboardInterrupt:
                print("\nExiting...")
                return False
        else:
            print("ℹ️  No virtual environment detected.")
            print("For better dependency management, consider creating one:")
            print("   python3 setup_web_env.py")
            print()
    else:
        print(f"✓ Running in virtual environment: {sys.prefix}")

    return True

def check_dependencies():
    """Check if required dependencies are installed"""
    missing_deps = []

    try:
        import flask
    except ImportError:
        missing_deps.append('flask')

    try:
        import flask_socketio
    except ImportError:
        missing_deps.append('flask-socketio')

    try:
        import flask_cors
    except ImportError:
        missing_deps.append('flask-cors')

    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"   - {dep}")
        print()
        print("To install dependencies:")
        print("1. If using virtual environment:")
        print("   pip install " + " ".join(missing_deps))
        print()
        print("2. If not using virtual environment:")
        print("   python3 setup_web_env.py")
        print()
        return False

    return True

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hiber_proxy.web.app import create_app
from hiber_proxy.core.logging_config import setup_logging

def main():
    """Main entry point for web server"""
    print("🚀 Starting HiberProxy Enhanced Web Interface...")
    print()

    # Check virtual environment
    if not check_virtual_environment():
        return 1

    # Check dependencies
    if not check_dependencies():
        return 1

    print("✓ All dependencies available")
    print()

    # Setup logging
    setup_logging(log_level="INFO", enable_console=True, enable_file=True)
    
    try:
        # Create Flask app with SocketIO
        app, socketio = create_app()
        
        # Configuration
        host = os.environ.get('HIBER_WEB_HOST', '0.0.0.0')
        port = int(os.environ.get('HIBER_WEB_PORT', 5000))
        debug = os.environ.get('HIBER_WEB_DEBUG', 'False').lower() == 'true'
        
        print(f"Web interface will be available at: http://{host}:{port}")
        print("Press Ctrl+C to stop the server")
        
        # Start the server
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            allow_unsafe_werkzeug=True  # For development
        )
        
    except KeyboardInterrupt:
        print("\nShutting down web server...")
    except Exception as e:
        print(f"Error starting web server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
