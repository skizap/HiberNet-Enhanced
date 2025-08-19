# HiberProxy Enhanced Web Interface

A modern web interface for HiberProxy Enhanced with dark orange terminal aesthetic, real-time updates, and comprehensive analytics.

## Features

### 🎨 Dark Orange Terminal Aesthetic
- Dark background (#1a1a1a) with orange accents (#ff6600, #ff8533)
- Monospace fonts for authentic terminal feel
- Console-like styling throughout the interface
- Responsive design for desktop and mobile

### 📊 Real-time Dashboard
- Live system statistics and metrics
- Real-time proxy status updates via WebSocket
- Interactive charts and visualizations
- Quick action buttons for common tasks

### 🔧 Proxy Management
- View, filter, and search proxy lists
- Add, check, and remove proxies
- Bulk operations on selected proxies
- Real-time status updates

### ⚙️ Configuration Management
- Web-based configuration editor
- Live settings updates
- Import/export configuration
- Validation and error checking

### 📈 Advanced Analytics
- Performance metrics and trends
- Protocol distribution charts
- Response time analysis
- Historical data visualization

## Installation

### Prerequisites
- Python 3.7+
- HiberProxy Enhanced core system

### Recommended Setup (Virtual Environment)

**Option 1: Automatic Setup (Recommended)**
```bash
# Run the setup script to create virtual environment and install all dependencies
python3 setup_web_env.py

# Activate the environment
source activate_hiber_env.sh    # Linux/macOS
# OR
activate_hiber_env.bat          # Windows
```

**Option 2: Manual Setup**
```bash
# Create virtual environment
python3 -m venv hiber_venv

# Activate virtual environment
source hiber_venv/bin/activate  # Linux/macOS
# OR
hiber_venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements_enhanced.txt
pip install flask flask-socketio flask-cors
```

### Alternative: System-wide Installation
If you encounter "externally-managed-environment" errors on Debian/Ubuntu:
```bash
# Install system packages (limited functionality)
sudo apt install python3-flask python3-flask-socketio

# OR use pipx for isolated installation
pipx install flask flask-socketio flask-cors
```

### Required Dependencies
The web interface requires these packages:
- `flask>=2.0.0` - Web framework
- `flask-socketio>=5.0.0` - Real-time WebSocket support
- `flask-cors>=3.0.0` - Cross-origin resource sharing

### Quick Start
```bash
# If using virtual environment (recommended)
source activate_hiber_env.sh    # Activate environment first
python hiber_proxy/web/run_server.py

# If using system installation
python3 hiber_proxy/web/run_server.py
```

The web interface will be available at: http://localhost:5000

### Troubleshooting PEP 668 Errors
If you see "externally-managed-environment" errors:
1. **Use the automatic setup** (recommended): `python3 setup_web_env.py`
2. **Or create virtual environment manually** as shown above
3. **Or use system packages**: `sudo apt install python3-flask python3-flask-socketio`

## Configuration

### Environment Variables
- `HIBER_WEB_HOST` - Server host (default: 0.0.0.0)
- `HIBER_WEB_PORT` - Server port (default: 5000)
- `HIBER_WEB_DEBUG` - Debug mode (default: False)

### Example
```bash
export HIBER_WEB_HOST=127.0.0.1
export HIBER_WEB_PORT=8080
export HIBER_WEB_DEBUG=true
python hiber_proxy/web/run_server.py
```

## API Endpoints

### Statistics
- `GET /api/stats` - System statistics
- `GET /api/protocol-stats` - Protocol distribution

### Proxy Management
- `GET /api/proxies` - List proxies with filtering
- `POST /api/add` - Add a single proxy
- `POST /api/download` - Download proxies from sources
- `POST /api/check` - Check proxy connectivity
- `POST /api/cleanup` - Remove failed proxies

### Data Export
- `GET /api/export` - Export proxies (txt, json, csv)

### Sources
- `GET /api/sources` - Available proxy sources
- `POST /api/sources/test` - Test source availability

## File Structure

```
hiber_proxy/web/
├── __init__.py              # Web module initialization
├── app.py                   # Flask application factory
├── run_server.py            # Server launcher script
├── README.md                # This file
├── api/
│   ├── __init__.py          # API module
│   └── routes.py            # RESTful API endpoints
├── static/
│   ├── css/
│   │   └── style.css        # Dark orange terminal theme
│   └── js/
│       ├── main.js          # Main JavaScript functionality
│       └── websocket.js     # WebSocket client
└── templates/
    ├── base.html            # Base template
    ├── index.html           # Dashboard
    ├── proxies.html         # Proxy management
    ├── config.html          # Configuration
    └── analytics.html       # Analytics dashboard
```

## Usage

### Dashboard
- View system overview and statistics
- Quick actions for common tasks
- Real-time activity log
- Protocol distribution chart

### Proxy Management
- Filter by protocol, status, or limit
- Select multiple proxies for bulk operations
- Add new proxies manually
- Real-time status updates

### Configuration
- Edit system settings through web interface
- Validate configuration before saving
- Import/export configuration files
- Enable/disable proxy sources

### Analytics
- View performance trends over time
- Analyze response time distribution
- Monitor protocol usage
- Track system metrics

## Development

### Testing
```bash
# Run the test suite
python test_web_interface.py
```

### Adding New Features
1. Add API endpoints in `api/routes.py`
2. Create/update templates in `templates/`
3. Add JavaScript functionality in `static/js/`
4. Update CSS styling in `static/css/style.css`

### WebSocket Events
The interface uses WebSocket for real-time updates:
- `proxy_update` - Proxy status changes
- `stats_update` - Statistics updates
- `system_notification` - System messages

## Troubleshooting

### Common Issues

**Flask not found**
```bash
pip install flask flask-socketio flask-cors
```

**Permission denied on port 5000**
```bash
export HIBER_WEB_PORT=8080
python hiber_proxy/web/run_server.py
```

**WebSocket connection failed**
- Check firewall settings
- Ensure port is not blocked
- Try different port number

### Debug Mode
Enable debug mode for development:
```bash
export HIBER_WEB_DEBUG=true
python hiber_proxy/web/run_server.py
```

## Security Notes

- The web interface is designed for local use
- For production deployment, consider:
  - Adding authentication
  - Using HTTPS
  - Restricting access by IP
  - Running behind a reverse proxy

## Contributing

1. Follow the existing code style
2. Maintain the dark orange terminal aesthetic
3. Ensure responsive design
4. Add appropriate error handling
5. Update documentation

## License

Part of HiberProxy Enhanced - Multi-Protocol Proxy Management System
