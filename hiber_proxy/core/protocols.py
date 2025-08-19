"""
Multi-protocol proxy support for HiberProxy Enhanced

Provides protocol detection, connection handling, and proxy checking
for HTTP, HTTPS, SOCKS4, and SOCKS5 protocols with proper authentication.
"""

import socket
import ssl
import struct
import urllib.request
import urllib.error
import time
import threading
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum
import logging

from .exceptions import (
    ProxyConnectionError, ProxyAuthenticationError, ProtocolError,
    HiberProxyError
)
from .error_handler import handle_errors, error_context
from .user_agents import IntelligentUserAgentRotator, UserAgentCategory

logger = logging.getLogger(__name__)


class ProxyProtocol(Enum):
    """Supported proxy protocols"""
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


@dataclass
class ProxyCheckResult:
    """Result of proxy connectivity check"""
    success: bool
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    status_code: Optional[int] = None
    protocol_verified: bool = False
    
    @property
    def is_fast(self) -> bool:
        """Check if proxy response time is considered fast (< 5 seconds)"""
        return self.response_time is not None and self.response_time < 5.0


class ProtocolDetector:
    """Detects and classifies proxy protocols from proxy strings"""
    
    PROTOCOL_INDICATORS = {
        'http://': ProxyProtocol.HTTP,
        'https://': ProxyProtocol.HTTPS,
        'socks4://': ProxyProtocol.SOCKS4,
        'socks5://': ProxyProtocol.SOCKS5,
    }
    
    DEFAULT_PORTS = {
        80: ProxyProtocol.HTTP,
        443: ProxyProtocol.HTTPS,
        1080: ProxyProtocol.SOCKS5,  # Most common SOCKS port
        9050: ProxyProtocol.SOCKS5,  # Tor default
    }
    
    @classmethod
    def detect_protocol(cls, proxy_string: str, default: ProxyProtocol = ProxyProtocol.HTTP) -> ProxyProtocol:
        """
        Detect proxy protocol from string
        
        Args:
            proxy_string: Proxy string (various formats supported)
            default: Default protocol if detection fails
            
        Returns:
            Detected ProxyProtocol
        """
        proxy_lower = proxy_string.lower().strip()
        
        # Check for explicit protocol indicators
        for indicator, protocol in cls.PROTOCOL_INDICATORS.items():
            if proxy_lower.startswith(indicator):
                return protocol
        
        # Try to detect from port number
        try:
            # Extract port from host:port format
            if ':' in proxy_string:
                parts = proxy_string.split(':')
                if len(parts) >= 2:
                    port = int(parts[-1])
                    if port in cls.DEFAULT_PORTS:
                        return cls.DEFAULT_PORTS[port]
        except (ValueError, IndexError):
            pass
        
        return default
    
    @classmethod
    def get_default_port(cls, protocol: ProxyProtocol) -> int:
        """Get default port for a protocol"""
        port_map = {
            ProxyProtocol.HTTP: 80,
            ProxyProtocol.HTTPS: 443,
            ProxyProtocol.SOCKS4: 1080,
            ProxyProtocol.SOCKS5: 1080,
        }
        return port_map.get(protocol, 80)


class BaseProxyHandler:
    """Base class for proxy protocol handlers"""
    
    def __init__(self, host: str, port: int, username: Optional[str] = None,
                 password: Optional[str] = None, timeout: int = 30,
                 user_agent_rotator: Optional[IntelligentUserAgentRotator] = None):
        """
        Initialize proxy handler

        Args:
            host: Proxy host
            port: Proxy port
            username: Authentication username (optional)
            password: Authentication password (optional)
            timeout: Connection timeout in seconds
            user_agent_rotator: User agent rotation system (optional)
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.user_agent_rotator = user_agent_rotator
    
    def check_connectivity(self, test_url: str = "http://www.google.com") -> ProxyCheckResult:
        """
        Check proxy connectivity
        
        Args:
            test_url: URL to test connectivity against
            
        Returns:
            ProxyCheckResult with test results
        """
        raise NotImplementedError("Subclasses must implement check_connectivity")
    
    def _measure_response_time(self, func, *args, **kwargs) -> Tuple[Any, float]:
        """Measure execution time of a function"""
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            return result, end_time - start_time
        except Exception as e:
            end_time = time.time()
            raise e


class HTTPProxyHandler(BaseProxyHandler):
    """HTTP proxy connection handler"""
    
    @handle_errors(operation="http_proxy_check", max_retries=1, reraise=False)
    def check_connectivity(self, test_url: str = "http://www.google.com") -> ProxyCheckResult:
        """Check HTTP proxy connectivity"""
        try:
            with error_context("http_proxy_connection",
                             host=self.host, port=self.port, test_url=test_url):
                # Create proxy handler
                proxy_url = f"http://{self.host}:{self.port}"
                if self.username and self.password:
                    proxy_url = f"http://{self.username}:{self.password}@{self.host}:{self.port}"

                proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
                opener = urllib.request.build_opener(proxy_handler)

                # Create request with intelligent user agent
                request = urllib.request.Request(test_url)

                # Use intelligent user agent rotation if available
                if self.user_agent_rotator:
                    user_agent = self.user_agent_rotator.get_user_agent(
                        preferred_category=UserAgentCategory.CHROME
                    )
                else:
                    user_agent = 'HiberNet-Enhanced/2.0'

                request.add_header('User-Agent', user_agent)

                # Measure response time
                response, response_time = self._measure_response_time(
                    opener.open, request, timeout=self.timeout
                )

                status_code = response.getcode()

                return ProxyCheckResult(
                    success=True,
                    response_time=response_time,
                    status_code=status_code,
                    protocol_verified=True
                )

        except urllib.error.HTTPError as e:
            if e.code == 407:  # Proxy Authentication Required
                raise ProxyAuthenticationError(
                    message=f"Proxy authentication required: {e.reason}",
                    host=self.host,
                    port=self.port,
                    username=self.username
                )
            return ProxyCheckResult(
                success=False,
                error_message=f"HTTP Error {e.code}: {e.reason}",
                status_code=e.code
            )
        except urllib.error.URLError as e:
            raise ProxyConnectionError(
                message=f"Connection failed: {e.reason}",
                host=self.host,
                port=self.port,
                protocol="http",
                timeout=self.timeout
            )
        except Exception as e:
            raise ProxyConnectionError(
                message=f"Unexpected connection error: {str(e)}",
                host=self.host,
                port=self.port,
                protocol="http",
                timeout=self.timeout
            )


class HTTPSProxyHandler(BaseProxyHandler):
    """HTTPS proxy connection handler with SSL support"""
    
    def __init__(self, *args, verify_ssl: bool = False, **kwargs):
        """
        Initialize HTTPS proxy handler
        
        Args:
            verify_ssl: Whether to verify SSL certificates
        """
        super().__init__(*args, **kwargs)
        self.verify_ssl = verify_ssl
    
    def check_connectivity(self, test_url: str = "https://www.google.com") -> ProxyCheckResult:
        """Check HTTPS proxy connectivity"""
        try:
            # Create SSL context
            if self.verify_ssl:
                ssl_context = ssl.create_default_context()
            else:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create proxy handler
            proxy_url = f"http://{self.host}:{self.port}"
            if self.username and self.password:
                proxy_url = f"http://{self.username}:{self.password}@{self.host}:{self.port}"
            
            proxy_handler = urllib.request.ProxyHandler({'https': proxy_url})
            https_handler = urllib.request.HTTPSHandler(context=ssl_context)
            opener = urllib.request.build_opener(proxy_handler, https_handler)
            
            # Create request
            request = urllib.request.Request(test_url)
            request.add_header('User-Agent', 'HiberNet-Enhanced/2.0')
            
            # Measure response time
            response, response_time = self._measure_response_time(
                opener.open, request, timeout=self.timeout
            )
            
            status_code = response.getcode()
            
            return ProxyCheckResult(
                success=True,
                response_time=response_time,
                status_code=status_code,
                protocol_verified=True
            )
            
        except Exception as e:
            return ProxyCheckResult(
                success=False,
                error_message=f"HTTPS connection error: {str(e)}"
            )


class SOCKS4ProxyHandler(BaseProxyHandler):
    """SOCKS4 proxy connection handler"""
    
    def check_connectivity(self, test_url: str = "http://www.google.com") -> ProxyCheckResult:
        """Check SOCKS4 proxy connectivity"""
        try:
            # Parse test URL to get target host and port
            from urllib.parse import urlparse
            parsed = urlparse(test_url)
            target_host = parsed.hostname
            target_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            # Create socket connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            
            start_time = time.time()
            
            try:
                # Connect to SOCKS4 proxy
                sock.connect((self.host, self.port))
                
                # SOCKS4 handshake
                # Format: VER CMD DSTPORT DSTIP USERID NULL
                request = struct.pack('>BBH', 0x04, 0x01, target_port)  # VER, CMD, DSTPORT
                
                # Convert hostname to IP
                try:
                    target_ip = socket.gethostbyname(target_host)
                    request += socket.inet_aton(target_ip)
                except socket.gaierror:
                    # Use SOCKS4A for hostname resolution
                    request += struct.pack('>I', 0x00000001)  # Invalid IP for SOCKS4A
                
                request += b'\x00'  # NULL-terminated user ID
                
                # Add hostname for SOCKS4A
                if target_ip is None:
                    request += target_host.encode('ascii') + b'\x00'
                
                sock.send(request)
                
                # Read response
                response = sock.recv(8)
                if len(response) < 8:
                    raise Exception("Invalid SOCKS4 response")
                
                # Parse response: VER REP DSTPORT DSTIP
                ver, rep, dstport, dstip = struct.unpack('>BBH4s', response)
                
                if rep != 0x5A:  # Request granted
                    error_codes = {
                        0x5B: "Request rejected or failed",
                        0x5C: "Request failed because client is not running identd",
                        0x5D: "Request failed because client's identd could not confirm the user ID"
                    }
                    error_msg = error_codes.get(rep, f"SOCKS4 error code: {rep}")
                    raise Exception(error_msg)
                
                end_time = time.time()
                response_time = end_time - start_time
                
                return ProxyCheckResult(
                    success=True,
                    response_time=response_time,
                    protocol_verified=True
                )
                
            finally:
                sock.close()
                
        except Exception as e:
            return ProxyCheckResult(
                success=False,
                error_message=f"SOCKS4 connection error: {str(e)}"
            )


class SOCKS5ProxyHandler(BaseProxyHandler):
    """SOCKS5 proxy connection handler with authentication support"""
    
    def check_connectivity(self, test_url: str = "http://www.google.com") -> ProxyCheckResult:
        """Check SOCKS5 proxy connectivity"""
        try:
            # Parse test URL
            from urllib.parse import urlparse
            parsed = urlparse(test_url)
            target_host = parsed.hostname
            target_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            # Create socket connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            
            start_time = time.time()
            
            try:
                # Connect to SOCKS5 proxy
                sock.connect((self.host, self.port))
                
                # SOCKS5 authentication negotiation
                if self.username and self.password:
                    # Request username/password authentication
                    auth_request = struct.pack('>BBB', 0x05, 0x01, 0x02)  # VER, NMETHODS, USERNAME/PASSWORD
                else:
                    # Request no authentication
                    auth_request = struct.pack('>BBB', 0x05, 0x01, 0x00)  # VER, NMETHODS, NO AUTH
                
                sock.send(auth_request)
                
                # Read authentication response
                auth_response = sock.recv(2)
                if len(auth_response) != 2:
                    raise Exception("Invalid SOCKS5 authentication response")
                
                ver, method = struct.unpack('>BB', auth_response)
                if ver != 0x05:
                    raise Exception("Invalid SOCKS5 version")
                
                # Handle authentication
                if method == 0x02:  # Username/password authentication
                    if not (self.username and self.password):
                        raise Exception("Proxy requires authentication but no credentials provided")
                    
                    # Send username/password
                    username_bytes = self.username.encode('utf-8')
                    password_bytes = self.password.encode('utf-8')
                    
                    auth_data = struct.pack('>BB', 0x01, len(username_bytes))
                    auth_data += username_bytes
                    auth_data += struct.pack('>B', len(password_bytes))
                    auth_data += password_bytes
                    
                    sock.send(auth_data)
                    
                    # Read authentication result
                    auth_result = sock.recv(2)
                    if len(auth_result) != 2 or auth_result[1] != 0:
                        raise Exception("SOCKS5 authentication failed")
                
                elif method == 0xFF:
                    raise Exception("No acceptable authentication methods")
                
                # SOCKS5 connection request
                # Format: VER CMD RSV ATYP DST.ADDR DST.PORT
                request = struct.pack('>BBBB', 0x05, 0x01, 0x00, 0x03)  # VER, CMD, RSV, ATYP (domain name)
                request += struct.pack('>B', len(target_host)) + target_host.encode('ascii')
                request += struct.pack('>H', target_port)
                
                sock.send(request)
                
                # Read connection response
                response = sock.recv(4)
                if len(response) != 4:
                    raise Exception("Invalid SOCKS5 connection response")
                
                ver, rep, rsv, atyp = struct.unpack('>BBBB', response)
                
                if rep != 0x00:  # Success
                    error_codes = {
                        0x01: "General SOCKS server failure",
                        0x02: "Connection not allowed by ruleset",
                        0x03: "Network unreachable",
                        0x04: "Host unreachable",
                        0x05: "Connection refused",
                        0x06: "TTL expired",
                        0x07: "Command not supported",
                        0x08: "Address type not supported"
                    }
                    error_msg = error_codes.get(rep, f"SOCKS5 error code: {rep}")
                    raise Exception(error_msg)
                
                # Read remaining response data (address and port)
                if atyp == 0x01:  # IPv4
                    sock.recv(6)  # 4 bytes IP + 2 bytes port
                elif atyp == 0x03:  # Domain name
                    addr_len = struct.unpack('>B', sock.recv(1))[0]
                    sock.recv(addr_len + 2)  # domain + 2 bytes port
                elif atyp == 0x04:  # IPv6
                    sock.recv(18)  # 16 bytes IP + 2 bytes port
                
                end_time = time.time()
                response_time = end_time - start_time
                
                return ProxyCheckResult(
                    success=True,
                    response_time=response_time,
                    protocol_verified=True
                )
                
            finally:
                sock.close()
                
        except Exception as e:
            return ProxyCheckResult(
                success=False,
                error_message=f"SOCKS5 connection error: {str(e)}"
            )


class ProxyChecker:
    """Multi-protocol proxy checker with concurrent testing support"""
    
    def __init__(self, timeout: int = 30, max_concurrent: int = 50,
                 enable_user_agent_rotation: bool = True):
        """
        Initialize proxy checker

        Args:
            timeout: Connection timeout in seconds
            max_concurrent: Maximum concurrent checks
            enable_user_agent_rotation: Enable intelligent user agent rotation
        """
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)

        # Initialize user agent rotator
        if enable_user_agent_rotation:
            self.user_agent_rotator = IntelligentUserAgentRotator(
                min_rotation_interval=300,  # 5 minutes
                max_same_agent_usage=10,
                detection_threshold=20.0
            )
        else:
            self.user_agent_rotator = None

        # Protocol handlers
        self.handlers = {
            ProxyProtocol.HTTP: HTTPProxyHandler,
            ProxyProtocol.HTTPS: HTTPSProxyHandler,
            ProxyProtocol.SOCKS4: SOCKS4ProxyHandler,
            ProxyProtocol.SOCKS5: SOCKS5ProxyHandler,
        }
    
    def check_proxy(self, host: str, port: int, protocol: ProxyProtocol,
                   username: Optional[str] = None, password: Optional[str] = None,
                   test_url: Optional[str] = None) -> ProxyCheckResult:
        """
        Check a single proxy
        
        Args:
            host: Proxy host
            port: Proxy port
            protocol: Proxy protocol
            username: Authentication username (optional)
            password: Authentication password (optional)
            test_url: Custom test URL (optional)
            
        Returns:
            ProxyCheckResult with test results
        """
        with self._semaphore:
            try:
                # Get appropriate handler
                handler_class = self.handlers.get(protocol)
                if not handler_class:
                    return ProxyCheckResult(
                        success=False,
                        error_message=f"Unsupported protocol: {protocol.value}"
                    )
                
                # Create handler instance
                handler = handler_class(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=self.timeout,
                    user_agent_rotator=self.user_agent_rotator
                )
                
                # Determine test URL
                if test_url is None:
                    if protocol == ProxyProtocol.HTTPS:
                        test_url = "https://www.google.com"
                    else:
                        test_url = "http://www.google.com"
                
                # Perform check
                result = handler.check_connectivity(test_url)

                # Report result to user agent rotator
                if self.user_agent_rotator:
                    self.user_agent_rotator.report_result(
                        success=result.success,
                        detected=(result.status_code == 403 or 'blocked' in str(result.error_message).lower())
                    )

                logger.debug(f"Proxy check: {host}:{port} ({protocol.value}) - "
                           f"Success: {result.success}, Time: {result.response_time}")

                return result
                
            except Exception as e:
                logger.error(f"Unexpected error checking proxy {host}:{port}: {e}")
                return ProxyCheckResult(
                    success=False,
                    error_message=f"Unexpected error: {str(e)}"
                )
    
    def check_multiple_protocols(self, host: str, port: int,
                                protocols: List[ProxyProtocol],
                                username: Optional[str] = None,
                                password: Optional[str] = None) -> Dict[ProxyProtocol, ProxyCheckResult]:
        """
        Check a proxy against multiple protocols
        
        Args:
            host: Proxy host
            port: Proxy port
            protocols: List of protocols to test
            username: Authentication username (optional)
            password: Authentication password (optional)
            
        Returns:
            Dictionary mapping protocols to check results
        """
        results = {}
        
        for protocol in protocols:
            result = self.check_proxy(host, port, protocol, username, password)
            results[protocol] = result
            
            # If we find a working protocol, we can stop (optional optimization)
            if result.success:
                logger.debug(f"Found working protocol {protocol.value} for {host}:{port}")
        
        return results
    
    def get_best_protocol(self, host: str, port: int,
                         protocols: Optional[List[ProxyProtocol]] = None,
                         username: Optional[str] = None,
                         password: Optional[str] = None) -> Tuple[Optional[ProxyProtocol], Optional[ProxyCheckResult]]:
        """
        Find the best working protocol for a proxy
        
        Args:
            host: Proxy host
            port: Proxy port
            protocols: List of protocols to test (default: all)
            username: Authentication username (optional)
            password: Authentication password (optional)
            
        Returns:
            Tuple of (best_protocol, check_result) or (None, None) if none work
        """
        if protocols is None:
            protocols = list(ProxyProtocol)
        
        results = self.check_multiple_protocols(host, port, protocols, username, password)
        
        # Find the best result (working + fastest)
        working_results = [(proto, result) for proto, result in results.items() if result.success]
        
        if not working_results:
            return None, None
        
        # Sort by response time (fastest first)
        working_results.sort(key=lambda x: x[1].response_time or float('inf'))
        
        best_protocol, best_result = working_results[0]
        return best_protocol, best_result

    def get_user_agent_stats(self) -> Optional[Dict[str, Any]]:
        """Get user agent rotation statistics"""
        if not self.user_agent_rotator:
            return None

        stats = self.user_agent_rotator.get_rotation_stats()
        return {
            'total_requests': stats.total_requests,
            'unique_agents_used': stats.unique_agents_used,
            'category_distribution': stats.category_distribution,
            'average_success_rate': stats.average_success_rate,
            'detection_incidents': stats.detection_incidents,
            'last_rotation_time': stats.last_rotation_time.isoformat() if stats.last_rotation_time else None,
            'current_agent': self.user_agent_rotator.current_agent[:50] + '...' if self.user_agent_rotator.current_agent else None
        }
