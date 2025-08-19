# HiberProxy Enhanced

A comprehensive multi-protocol proxy management system with database integration, advanced validation, and intelligent analytics.

## 🚀 Features

### Phase 1: Core Infrastructure (✅ COMPLETED)

- **Multi-Protocol Support**: HTTP, HTTPS, SOCKS4, and SOCKS5 protocols
- **Database Integration**: SQLite database with connection pooling and statistics tracking
- **Enhanced Validation**: Comprehensive IP/port validation and proxy format parsing
- **Advanced Logging**: Structured logging with multiple handlers and configurable levels
- **Protocol Detection**: Automatic detection and classification of proxy types
- **Statistics Tracking**: Performance metrics, success rates, and usage analytics

### Phase 2: Enhanced Scraping & User Experience (✅ COMPLETED)

- **GitHub Proxy Scraping**: Automated downloading from multiple GitHub repositories
- **Multi-Source Support**: TheSpeedX, monosans, databay-labs, zloi-user repositories
- **Rate Limiting**: Ethical scraping with configurable delays and retry logic
- **Source Management**: Database tracking of scraping statistics and success rates
- **Protocol Filtering**: Download specific protocols or repositories
- **Duplicate Detection**: Intelligent handling of duplicate proxies

### Coming Soon (Phase 3-4)

- **Web Interface**: Modern dark orange terminal aesthetic dashboard
- **Real-time Analytics**: Live proxy performance monitoring
- **Export Formats**: JSON, CSV, XML export capabilities
- **User Agent Rotation**: Advanced detection avoidance
- **Memory Optimization**: Efficient handling of large proxy lists

## 📦 Installation

### Requirements

- Python 3.7+
- SQLite (built-in)
- Required packages (see `requirements_enhanced.txt`)

### Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements_enhanced.txt
   ```

2. **Run the enhanced system:**
   ```bash
   # Interactive mode (backward compatible)
   python HiberProxy_Enhanced.py
   
   # Command-line interface
   python -m hiber_proxy.main --help
   ```

3. **Migrate existing proxy.txt files:**
   ```bash
   python -m hiber_proxy.main migrate proxy.txt
   ```

## 🔧 Usage

### Command Line Interface

```bash
# Download proxies from GitHub sources
python -m hiber_proxy.main download  # Download from all sources
python -m hiber_proxy.main download --protocol socks5  # Download SOCKS5 only
python -m hiber_proxy.main download --repository thespeedx  # Download from specific repo
python -m hiber_proxy.main download --test-sources  # Test source availability

# Migrate legacy proxy files
python -m hiber_proxy.main migrate proxy.txt socks_proxies.txt

# Add a single proxy
python -m hiber_proxy.main add "http://127.0.0.1:8080"
python -m hiber_proxy.main add "socks5://user:pass@proxy.example.com:1080"

# Check proxy connectivity
python -m hiber_proxy.main check --protocol http --limit 100
python -m hiber_proxy.main check --all  # Check all proxies including non-working

# List proxies
python -m hiber_proxy.main list --working-only
python -m hiber_proxy.main list --protocol socks5 --format json

# Export proxies
python -m hiber_proxy.main export working_proxies.txt --protocol http
python -m hiber_proxy.main export all_proxies.txt --all --include-auth

# Show statistics
python -m hiber_proxy.main stats

# Cleanup failed proxies
python -m hiber_proxy.main cleanup --max-failures 3

# Configuration management
python -m hiber_proxy.main config --create-default config.yaml
```

### Interactive Mode

```bash
python HiberProxy_Enhanced.py
```

The interactive mode provides a menu-driven interface similar to the original HiberProxy.py:

1. Download proxies from sources
2. Check existing proxies
3. List proxies
4. Add custom proxy
5. Export proxies
6. Show statistics
7. Cleanup failed proxies
8. Exit

### Python API

```python
from hiber_proxy.main import HiberProxyApp
from hiber_proxy.core.protocols import ProxyProtocol

# Initialize the application
app = HiberProxyApp()

# Add a proxy
proxy_id = app.add_proxy("http://127.0.0.1:8080")

# Check proxies
results = app.check_proxies(protocol="http", limit=50)

# Get statistics
stats = app.get_statistics()

# List working proxies
proxies = app.list_proxies(working_only=True)

# Export to file
app.export_proxies("working_proxies.txt", working_only=True)

# Clean up
app.close()
```

## 📊 Database Schema

The enhanced system uses SQLite with the following tables:

- **proxies**: Core proxy information (host, port, protocol, auth, location)
- **proxy_stats**: Performance statistics (success/failure counts, response times)
- **proxy_sources**: Source management (URLs, scraping intervals, success rates)

## 🔧 Configuration

Create a configuration file using:

```bash
python -m hiber_proxy.main config --create-default config.yaml
```

Example configuration:

```yaml
database:
  path: "hiber_proxy.db"
  connection_pool_size: 10
  timeout: 30

logging:
  level: "INFO"
  log_dir: "logs"
  enable_console: true
  enable_file: true
  enable_json: false

checking:
  timeout: 60
  test_url: "http://www.google.com"
  concurrent_checks: 50
  max_failures: 5

validation:
  strict_ip_validation: true
  allow_private_ips: false
  allow_localhost: false
```

## 🔍 Supported Proxy Formats

The system automatically detects and parses various proxy formats:

- `host:port`
- `protocol://host:port`
- `host:port:username:password`
- `protocol://username:password@host:port`

Supported protocols:
- **HTTP**: Standard HTTP proxies
- **HTTPS**: HTTPS proxies with SSL support
- **SOCKS4**: SOCKS4 protocol with hostname resolution
- **SOCKS5**: SOCKS5 with authentication support

## 🌐 **GitHub Proxy Sources**

The system automatically downloads proxies from these established GitHub repositories:

### **TheSpeedX SOCKS-List**
- **Repository**: https://github.com/TheSpeedX/SOCKS-List
- **Protocols**: SOCKS5, SOCKS4, HTTP
- **Update Frequency**: Regular updates with thousands of proxies

### **monosans proxy-list**
- **Repository**: https://github.com/monosans/proxy-list
- **Protocols**: SOCKS5, SOCKS4, HTTP
- **Update Frequency**: Daily updates with verified proxies

### **databay-labs free-proxy-list**
- **Repository**: https://github.com/databay-labs/free-proxy-list
- **Protocols**: HTTP, HTTPS, SOCKS5
- **Update Frequency**: Regular updates with categorized proxies

### **zloi-user hideip.me**
- **Repository**: https://github.com/zloi-user/hideip.me
- **Protocols**: SOCKS5, SOCKS4, HTTPS, HTTP, CONNECT
- **Update Frequency**: Frequent updates with global proxy coverage

## 📈 Statistics and Analytics

The system tracks comprehensive statistics:

- **Proxy Performance**: Success rates, response times, failure counts
- **Protocol Distribution**: Breakdown by proxy type
- **Source Analytics**: Success rates for different proxy sources
- **Usage Patterns**: Last used timestamps, check frequencies

## 🔄 Migration from Legacy

The enhanced system is fully backward compatible:

1. **Automatic Migration**: Detects existing `proxy.txt` files and offers migration
2. **Format Preservation**: Maintains all existing proxy data
3. **Backup Creation**: Creates backup of original files
4. **Interactive Mode**: Familiar menu-driven interface

## 🛠️ Development

### Project Structure

```
hiber_proxy/
├── __init__.py
├── core/
│   ├── database.py          # Database management
│   ├── logging_config.py    # Logging system
│   ├── validation.py        # Proxy validation
│   └── protocols.py         # Protocol handlers
├── utils/
│   ├── config.py           # Configuration management
│   └── migration.py        # Legacy migration
└── main.py                 # CLI interface
```

### Adding New Features

1. **New Protocol Support**: Extend `protocols.py` with new handler classes
2. **Custom Validation**: Add rules to `validation.py`
3. **Database Changes**: Update schema in `database.py`
4. **Configuration**: Add new settings to `config.py`

## 🔒 Security Considerations

- **No Credential Storage**: Passwords are stored securely in the database
- **SSL Verification**: Configurable SSL certificate validation
- **Input Validation**: Comprehensive validation of all inputs
- **Error Handling**: Graceful handling of network errors and timeouts

## 📝 Logging

The system provides structured logging with:

- **Multiple Handlers**: Console, file, and rotating file handlers
- **Configurable Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **JSON Format**: Optional structured JSON logging
- **Component Separation**: Separate loggers for different components

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project maintains the same license as the original Hibernet project.

## 🙏 Acknowledgments

- Original HiberProxy.py authors
- Hibernet project contributors
- Python networking and database communities

---

**HiberProxy Enhanced** - Taking proxy management to the next level! 🚀
