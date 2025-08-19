# HibernetV3.0 - Enhanced Network Stress Testing Tool

**HibernetV3.0** is a modernized, professional-grade network stress testing tool designed for security researchers, penetration testers, and network administrators who need to test their own infrastructure and networks they have authorization to test.

## 🚀 **What's New in V3.0**

### **Phase 1: Core Protocol Improvements**
- ✅ **Complete HTTP/2 Implementation**: Fixed and enhanced HTTP/2 support with proper error handling, connection management, and full HTTP/2 specification compliance
- ✅ **Enhanced HTTP/1.1 Support**: Improved connection pooling, keep-alive management, and proper header handling

### **Phase 2: Modern Protocol Support**
- ✅ **HTTP/3 (QUIC) Support**: Full HTTP/3 protocol support using aioquic library for testing modern web servers
- ✅ **WebSocket Stress Testing**: Complete WebSocket protocol support for testing real-time applications, chat systems, and streaming services

### **Phase 3: Advanced Infrastructure**
- ✅ **Advanced Proxy Management**: Intelligent proxy rotation algorithms, authentication support, proxy chaining, geographic distribution, and real-time performance monitoring
- ✅ **Comprehensive Real-time Metrics**: Professional metrics system with real-time dashboards, detailed statistics, error analysis, and multiple export formats

## 🛠️ **Installation**

### **Requirements**
```bash
pip install h2 aioquic websockets geoip2
```

### **Optional Dependencies**
- `h2`: For HTTP/2 support
- `aioquic`: For HTTP/3 (QUIC) support
- `websockets`: For WebSocket stress testing
- `geoip2`: For proxy geolocation features

## 📋 **Usage**

### **Modern CLI Interface**

#### **Basic HTTP Stress Test**
```bash
python HibernetV3.0.py --target https://example.com --threads 500 --duration 60
```

#### **Advanced Test with Proxies and HTTP/2**
```bash
python HibernetV3.0.py --target https://example.com --proxy-file proxies.txt --protocol http2 --real-time-dashboard
```

#### **WebSocket Stress Test**
```bash
python HibernetV3.0.py --target ws://example.com/chat --test-type websocket --connections 100
```

#### **Multiple Targets with Advanced Features**
```bash
python HibernetV3.0.py --target-file targets.txt --proxy-rotation health_based --export-json report.json
```

### **Legacy Interactive Mode**
Run without arguments for the original interactive interface:
```bash
python HibernetV3.0.py
```

## 🎯 **Key Features**

### **Protocol Support**
- **HTTP/1.1**: Enhanced with connection pooling and keep-alive management
- **HTTP/2**: Complete implementation with proper multiplexing and server push
- **HTTP/3 (QUIC)**: Modern protocol support for next-generation web servers
- **WebSocket**: Full support for real-time application testing

### **Advanced Proxy Management**
- **Intelligent Rotation**: Round-robin, weighted random, health-based, geographic, least-used, and fastest algorithms
- **Authentication**: Username/password support for authenticated proxies
- **Health Monitoring**: Real-time proxy performance tracking and automatic failover
- **Geographic Distribution**: GeoIP-based proxy selection and routing
- **Proxy Chaining**: Support for multiple proxy hops (planned)

### **Real-time Metrics & Reporting**
- **Live Dashboard**: Real-time statistics display with configurable update intervals
- **Comprehensive Metrics**: Request rates, response times, success rates, bandwidth usage
- **Error Analysis**: Detailed error categorization and failure analysis
- **Multiple Export Formats**: CSV, JSON, and HTML reports
- **Performance History**: Historical data tracking and trend analysis

### **Professional Features**
- **Session Management**: Named test sessions with full configuration tracking
- **Rate Limiting**: Configurable requests per second limits
- **Connection Pooling**: Efficient HTTP/1.1 connection reuse
- **Custom Headers**: Support for custom user agents and headers
- **Configuration Files**: JSON-based configuration management

## 📊 **Command Line Options**

### **Target Configuration**
- `--target, -t`: Single target URL or IP
- `--target-file, -tf`: File containing multiple targets

### **Test Configuration**
- `--threads, -th`: Number of threads (default: 800)
- `--duration, -d`: Test duration in seconds (default: 60)
- `--rate-limit, -r`: Requests per second limit per thread
- `--multiplication, -m`: Request multiplication factor (default: 1)

### **Protocol Options**
- `--protocol, -p`: HTTP protocol version (http1, http2, http3, auto)
- `--test-type`: Type of stress test (http_flood, websocket, mixed)

### **Proxy Configuration**
- `--proxy-file, -pf`: Proxy list file
- `--proxy-type`: Proxy type (http, socks4, socks5)
- `--proxy-rotation`: Rotation strategy (round_robin, weighted_random, health_based, fastest)

### **Output and Reporting**
- `--real-time-dashboard, -rtd`: Enable real-time dashboard
- `--dashboard-interval`: Dashboard update interval in seconds
- `--export-csv`: Export metrics to CSV file
- `--export-json`: Export comprehensive report to JSON file
- `--session-id`: Custom session ID

### **Advanced Options**
- `--user-agents-file`: Custom user agents file
- `--headers-file`: Custom headers file
- `--geoip-db`: GeoIP database file for proxy geolocation
- `--config-file, -c`: Configuration file (JSON format)
- `--quiet, -q`: Suppress output except errors
- `--verbose, -v`: Verbose output

## 📁 **File Formats**

### **Proxy File Format**
```
# HTTP Proxies
192.168.1.1:8080
proxy.example.com:3128

# Authenticated Proxies
username:password@proxy.example.com:8080

# SOCKS Proxies (specify with --proxy-type socks5)
socks.example.com:1080
```

### **Target File Format**
```
https://example1.com
https://example2.com/api
http://192.168.1.100:8080
ws://websocket.example.com/chat
```

### **Configuration File Format (JSON)**
```json
{
  "threads": 1000,
  "duration": 120,
  "protocol": "http2",
  "proxy_file": "proxies.txt",
  "proxy_rotation": "health_based",
  "real_time_dashboard": true,
  "dashboard_interval": 3.0,
  "geoip_db": "/path/to/GeoLite2-City.mmdb"
}
```

## 📈 **Real-time Dashboard**

The real-time dashboard provides live monitoring of your stress test:

```
================================================================================
HIBERNET V3.0 - REAL-TIME STATISTICS
================================================================================
Session: test-001 | Elapsed: 45.2s | Active: true

REQUESTS:
  Total: 125,430 | Success: 124,891 | Failed: 539
  Success Rate: 99.57% | RPS: 2,776.3 | Current RPS: 2,850.1

RESPONSE TIMES (ms):
  Avg: 45.2 | Min: 12.1 | Max: 1,205.3
  P50: 38.7 | P95: 89.4 | P99: 156.8

BANDWIDTH:
  Sent: 15,678,900 bytes | Received: 45,234,567 bytes
  Total: 60,913,467 bytes

PROTOCOLS:
  HTTP/2: 89,234
  HTTP/1.1: 36,196

STATUS CODES:
  200: 124,891
  503: 421
  502: 118

TOP ERRORS:
  Connection timeout: 245
  Proxy connection failed: 156
  SSL handshake failed: 89
================================================================================
```

## 🔧 **Advanced Configuration**

### **Proxy Rotation Strategies**

1. **Round Robin**: Cycles through proxies in order
2. **Weighted Random**: Random selection based on proxy priority and health
3. **Health Based**: Selects from top-performing proxies
4. **Geographic**: Routes based on proxy location
5. **Least Used**: Selects least recently used proxies
6. **Fastest**: Selects proxies with lowest response times

### **HTTP/2 Features**
- Full multiplexing support
- Server push simulation
- Proper flow control
- Settings negotiation
- ALPN protocol negotiation

### **HTTP/3 Features**
- QUIC transport protocol
- 0-RTT connection establishment
- Built-in encryption
- Connection migration support

### **WebSocket Features**
- Text and binary message support
- Ping/pong frame handling
- Connection keep-alive
- Graceful connection closure
- Custom message patterns

## 📊 **Metrics and Analytics**

### **Request Metrics**
- Total requests sent/received
- Success/failure rates
- Response time statistics (avg, min, max, percentiles)
- Requests per second (current and average)
- Bandwidth utilization

### **Proxy Analytics**
- Proxy health scores
- Success rates per proxy
- Average response times
- Geographic distribution
- Failure categorization

### **Error Analysis**
- Error type categorization
- Failure rate trends
- Connection issues
- Protocol-specific errors
- Proxy-related failures

## 🛡️ **Security and Safety**

### **Built-in Safeguards**
- Target validation and confirmation prompts
- Rate limiting to prevent system overload
- Connection limits and timeouts
- Graceful shutdown mechanisms
- Resource cleanup and management

### **Responsible Use**
- **Only test systems you own or have explicit authorization to test**
- Start with low intensity and gradually increase
- Monitor system resources during testing
- Have emergency stop procedures in place
- Document and analyze results for capacity planning

## 🤝 **Contributing**

This tool is designed for legitimate security testing and network analysis. Contributions that enhance security testing capabilities, improve performance, or add professional features are welcome.

## ⚖️ **Legal Disclaimer**

This tool is intended for authorized security testing and network analysis only. Users are responsible for ensuring they have proper authorization before testing any systems. Unauthorized use may violate local, state, and federal laws.

## 📝 **License**

This project is provided for educational and authorized testing purposes only. Use responsibly and in accordance with applicable laws and regulations.

---

**HibernetV3.0** - Professional Network Stress Testing for Security Researchers


<h2>Install dependencies</h2>
To use it you have to use python3 and you also need an extra module.

To install it if you are running linux or mac, type:
<pre>pip3 install pysocks</pre>

If you are under winzoz, type:
<pre>py -m pip install pysocks</pre>

<h2>Usage</h2>
Just type on a terminal:
<pre>python3 HibernetV3.x</pre>

Or double click on the program in winzoz.


<h2>New functionality for multi target attack.</h2>
Just put your IPs or urls inside "ips.txt"

<h2>Proxy generator</h2>
If you want more proxies for your attacks, you can use HiberProxy or HiberSOCKS!

You can found it here: https://github.com/All3xJ/HiberProxy and here: https://github.com/All3xJ/HiberSOCKS


<h1>ENJOY!</h1>



![alt text](https://i.imgur.com/odr1rPd.png)
![alt text](https://i.imgur.com/3YNngR0.png)
![alt text](https://i.imgur.com/BcvW4C3.png)


Attack from just 1 lousy vps can be dangerous for a target, so don't aim targets that are not your property.



<h2>Demonstration video:</h2>
https://www.youtube.com/watch?v=G84R0qKMpO8
