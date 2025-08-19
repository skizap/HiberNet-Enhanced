# HiberProxy Enhanced Virtual Environment Setup

## Problem Solved

This document explains how we resolved the "externally-managed-environment" error (PEP 668) that prevents direct pip installations on modern Debian/Ubuntu systems.

### The Error
```
error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try apt install
    python3-xyz, where xyz is the package you are trying to
    install.

    If you wish to install a non-Debian-packaged Python package,
    create a virtual environment using python3 -m venv path/to/venv.
    Then use path/to/venv/bin/pip install xyz.
```

### The Solution

We created a comprehensive virtual environment setup that:
1. ✅ Creates an isolated Python environment
2. ✅ Installs all required dependencies
3. ✅ Provides easy activation scripts
4. ✅ Includes comprehensive testing
5. ✅ Works cross-platform (Linux, macOS, Windows)

## Quick Start

### Option 1: Automatic Setup (Recommended)
```bash
# Run the setup script
python3 setup_web_env.py

# Activate the environment
source activate_hiber_env.sh

# Start the web interface
python hiber_proxy/web/run_server.py
```

### Option 2: Manual Setup
```bash
# Create virtual environment
python3 -m venv hiber_venv

# Activate it
source hiber_venv/bin/activate

# Install dependencies
pip install -r requirements_enhanced.txt

# Start the web interface
python hiber_proxy/web/run_server.py
```

## Files Created

### Setup Scripts
- `setup_web_env.sh` - Bash setup script (Linux/macOS)
- `setup_web_env.py` - Python setup script (cross-platform)
- `activate_hiber_env.sh` - Environment activation script

### Requirements Files
- `requirements_enhanced.txt` - Updated with web dependencies
- `requirements_web_interface.txt` - Complete web interface requirements
- `requirements_web.txt` - Generated from virtual environment

### Test Scripts
- `test_virtual_environment.py` - Comprehensive environment testing
- `test_web_interface.py` - Original web interface testing

### Updated Components
- `hiber_proxy/web/run_server.py` - Enhanced with environment detection
- `hiber_proxy/web/README.md` - Updated with virtual environment instructions

## Virtual Environment Structure

```
hiber_venv/                    # Virtual environment directory
├── bin/                       # Executables (Linux/macOS)
│   ├── python                 # Python interpreter
│   ├── pip                    # Package installer
│   └── activate               # Activation script
├── lib/                       # Python packages
│   └── python3.12/
│       └── site-packages/     # Installed packages
└── pyvenv.cfg                 # Environment configuration
```

## Dependencies Installed

### Core HiberProxy Dependencies
- `beautifulsoup4>=4.9.0` - HTML parsing
- `requests>=2.25.0` - HTTP requests
- `urllib3>=1.26.0` - HTTP client
- `pyyaml>=5.4.0` - YAML configuration
- `psutil>=5.8.0` - System monitoring

### Web Interface Dependencies
- `flask>=2.0.0` - Web framework
- `flask-socketio>=5.0.0` - Real-time WebSocket support
- `flask-cors>=3.0.0` - Cross-origin resource sharing

### Development Dependencies
- `pytest>=6.0.0` - Testing framework
- `pytest-cov>=2.10.0` - Coverage testing
- `black>=21.0.0` - Code formatting
- `flake8>=3.8.0` - Code linting

## Usage Instructions

### Daily Usage
```bash
# Activate environment
source activate_hiber_env.sh

# Start web interface
python hiber_proxy/web/run_server.py

# Open browser to http://localhost:5000
```

### Development Workflow
```bash
# Activate environment
source activate_hiber_env.sh

# Install new packages
pip install package_name

# Update requirements
pip freeze > requirements_web.txt

# Run tests
python test_virtual_environment.py

# Deactivate when done
deactivate
```

## Environment Detection

The updated `run_server.py` automatically:
- ✅ Detects if running in virtual environment
- ✅ Warns if virtual environment exists but not activated
- ✅ Checks for required dependencies
- ✅ Provides helpful error messages and suggestions

## Testing

### Comprehensive Test Suite
```bash
python3 test_virtual_environment.py
```

Tests verify:
- ✅ Virtual environment exists and is configured
- ✅ All dependencies are installed correctly
- ✅ HiberProxy Enhanced imports and initializes
- ✅ Web interface imports and creates Flask app
- ✅ Activation scripts are present

### Manual Testing
```bash
# Test Flask import
hiber_venv/bin/python -c "import flask; print('Flask OK')"

# Test HiberProxy import
hiber_venv/bin/python -c "from hiber_proxy.main import HiberProxyApp; print('HiberProxy OK')"

# Test web interface
hiber_venv/bin/python hiber_proxy/web/run_server.py
```

## Troubleshooting

### Common Issues

**1. Virtual environment not found**
```bash
# Solution: Run setup script
python3 setup_web_env.py
```

**2. Permission denied**
```bash
# Solution: Make scripts executable
chmod +x setup_web_env.sh activate_hiber_env.sh
```

**3. Missing python3-venv**
```bash
# Solution: Install venv module
sudo apt update && sudo apt install python3-venv
```

**4. Import errors**
```bash
# Solution: Activate environment first
source activate_hiber_env.sh
python hiber_proxy/web/run_server.py
```

### Alternative Solutions

**System packages (limited functionality):**
```bash
sudo apt install python3-flask python3-flask-socketio
```

**pipx (isolated installation):**
```bash
pipx install flask flask-socketio flask-cors
```

## Benefits of This Setup

### ✅ Advantages
- **Isolated environment** - No conflicts with system packages
- **Reproducible** - Same environment across different systems
- **Easy management** - Simple activation/deactivation
- **Complete dependencies** - All required packages included
- **Cross-platform** - Works on Linux, macOS, Windows
- **PEP 668 compliant** - Follows modern Python standards

### 🔧 Features
- **Automatic detection** - Smart environment detection
- **Comprehensive testing** - Full test suite included
- **Easy activation** - Simple activation scripts
- **Clear documentation** - Step-by-step instructions
- **Error handling** - Helpful error messages

## Next Steps

1. **Start the web interface:**
   ```bash
   source activate_hiber_env.sh
   python hiber_proxy/web/run_server.py
   ```

2. **Open your browser to:**
   ```
   http://localhost:5000
   ```

3. **Enjoy the dark orange terminal aesthetic!** 🎨

## Support

If you encounter any issues:
1. Run the test suite: `python3 test_virtual_environment.py`
2. Check the troubleshooting section above
3. Recreate the environment: `python3 setup_web_env.py`

The virtual environment setup is now complete and ready for development! 🚀
