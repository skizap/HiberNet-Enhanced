"""
Comprehensive validation system for HiberProxy Enhanced

Provides IP address validation, port validation, proxy format parsing,
and configurable validation rules for different proxy types and sources.
"""

import re
import ipaddress
import socket
from typing import Optional, Dict, List, Tuple, Union, Any
from dataclasses import dataclass
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


@dataclass
@dataclass
class ValidationRule:
    """Configurable validation rule"""
    name: str
    enabled: bool = True
    strict: bool = False
    custom_params: Dict[str, Any] = None

    def __post_init__(self):
        if self.custom_params is None:
            self.custom_params = {}


class IPValidator:
    """IP address validation with IPv4 and IPv6 support"""
    
    # IPv4 regex pattern
    IPV4_PATTERN = re.compile(
        r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    )
    
    # IPv6 regex pattern (simplified)
    IPV6_PATTERN = re.compile(
        r'^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|'
        r'^::1$|^::$|'
        r'^(?:[0-9a-fA-F]{1,4}:)*::(?:[0-9a-fA-F]{1,4}:)*[0-9a-fA-F]{1,4}$'
    )
    
    # Private IP ranges (IPv4)
    PRIVATE_RANGES = [
        ipaddress.IPv4Network('10.0.0.0/8'),
        ipaddress.IPv4Network('172.16.0.0/12'),
        ipaddress.IPv4Network('192.168.0.0/16'),
        ipaddress.IPv4Network('127.0.0.0/8'),  # Loopback
        ipaddress.IPv4Network('169.254.0.0/16'),  # Link-local
    ]
    
    @classmethod
    def validate_ipv4(cls, ip: str, allow_private: bool = False, 
                     allow_localhost: bool = False) -> bool:
        """
        Validate IPv4 address
        
        Args:
            ip: IP address string
            allow_private: Allow private IP ranges
            allow_localhost: Allow localhost/loopback addresses
            
        Returns:
            True if valid IPv4 address
        """
        if not cls.IPV4_PATTERN.match(ip):
            return False
        
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            
            # Check for private addresses
            if not allow_private:
                for private_range in cls.PRIVATE_RANGES:
                    if ip_obj in private_range:
                        if not allow_localhost or not ip_obj.is_loopback:
                            return False
            
            return True
            
        except ipaddress.AddressValueError:
            return False
    
    @classmethod
    def validate_ipv6(cls, ip: str) -> bool:
        """
        Validate IPv6 address
        
        Args:
            ip: IP address string
            
        Returns:
            True if valid IPv6 address
        """
        try:
            ipaddress.IPv6Address(ip)
            return True
        except ipaddress.AddressValueError:
            return False
    
    @classmethod
    def validate_ip(cls, ip: str, allow_private: bool = False, 
                   allow_localhost: bool = False) -> Tuple[bool, str]:
        """
        Validate IP address (IPv4 or IPv6)
        
        Args:
            ip: IP address string
            allow_private: Allow private IP ranges
            allow_localhost: Allow localhost addresses
            
        Returns:
            Tuple of (is_valid, ip_version)
        """
        # Try IPv4 first
        if cls.validate_ipv4(ip, allow_private, allow_localhost):
            return True, "ipv4"
        
        # Try IPv6
        if cls.validate_ipv6(ip):
            return True, "ipv6"
        
        return False, "unknown"
    
    @classmethod
    def is_private_ip(cls, ip: str) -> bool:
        """Check if IP address is in private range"""
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_private
        except ValueError:
            return False


class PortValidator:
    """Port number validation with protocol-specific ranges"""
    
    # Standard port ranges for different protocols
    PROTOCOL_PORTS = {
        'http': [80, 8080, 3128, 8000, 8888, 9999],
        'https': [443, 8443],
        'socks4': [1080, 9050, 9051],
        'socks5': [1080, 9050, 9051, 1085]
    }
    
    # Common proxy ports
    COMMON_PROXY_PORTS = [
        80, 443, 1080, 3128, 8000, 8080, 8443, 8888, 9050, 9051, 9999
    ]
    
    @classmethod
    def validate_port(cls, port: Union[int, str], 
                     protocol: Optional[str] = None,
                     strict_protocol_check: bool = False) -> bool:
        """
        Validate port number
        
        Args:
            port: Port number
            protocol: Protocol type for protocol-specific validation
            strict_protocol_check: Enforce protocol-specific port ranges
            
        Returns:
            True if valid port
        """
        try:
            port_num = int(port)
        except (ValueError, TypeError):
            return False
        
        # Basic range check
        if not (1 <= port_num <= 65535):
            return False
        
        # Protocol-specific validation
        if protocol and strict_protocol_check:
            allowed_ports = cls.PROTOCOL_PORTS.get(protocol.lower(), [])
            if allowed_ports and port_num not in allowed_ports:
                return False
        
        return True
    
    @classmethod
    def is_common_proxy_port(cls, port: Union[int, str]) -> bool:
        """Check if port is commonly used for proxies"""
        try:
            port_num = int(port)
            return port_num in cls.COMMON_PROXY_PORTS
        except (ValueError, TypeError):
            return False
    
    @classmethod
    def get_protocol_ports(cls, protocol: str) -> List[int]:
        """Get common ports for a specific protocol"""
        return cls.PROTOCOL_PORTS.get(protocol.lower(), [])


class ProxyFormatParser:
    """Parser for different proxy string formats"""
    
    # Regex patterns for different proxy formats
    PATTERNS = {
        'protocol_auth_host_port': re.compile(
            r'^(https?|socks[45]?)://([^:]+):([^@]+)@([^:]+):(\d+)$'
        ),
        'protocol_host_port': re.compile(
            r'^(https?|socks[45]?)://([^:]+):(\d+)$'
        ),
        'host_port_auth': re.compile(
            r'^([^:]+):(\d+):([^:]+):(.+)$'
        ),
        'host_port': re.compile(
            r'^([^:]+):(\d+)$'
        ),
        'url_format': re.compile(
            r'^(https?|socks[45]?)://([^:/]+)(?::(\d+))?(?:/.*)?$'
        )
    }
    
    @classmethod
    def parse_proxy_string(cls, proxy_string: str) -> Optional[Dict[str, str]]:
        """
        Parse proxy string into components
        
        Args:
            proxy_string: Proxy string in various formats
            
        Returns:
            Dictionary with proxy components or None if invalid
        """
        proxy_string = proxy_string.strip()
        
        # Try protocol://username:password@host:port
        match = cls.PATTERNS['protocol_auth_host_port'].match(proxy_string)
        if match:
            protocol, username, password, host, port = match.groups()
            return {
                'protocol': protocol.lower(),
                'host': host,
                'port': port,
                'username': username,
                'password': password
            }
        
        # Try protocol://host:port
        match = cls.PATTERNS['protocol_host_port'].match(proxy_string)
        if match:
            protocol, host, port = match.groups()
            return {
                'protocol': protocol.lower(),
                'host': host,
                'port': port,
                'username': None,
                'password': None
            }
        
        # Try host:port:username:password
        match = cls.PATTERNS['host_port_auth'].match(proxy_string)
        if match:
            host, port, username, password = match.groups()
            return {
                'protocol': 'http',  # Default protocol
                'host': host,
                'port': port,
                'username': username,
                'password': password
            }
        
        # Try host:port
        match = cls.PATTERNS['host_port'].match(proxy_string)
        if match:
            host, port = match.groups()
            return {
                'protocol': 'http',  # Default protocol
                'host': host,
                'port': port,
                'username': None,
                'password': None
            }
        
        # Try URL format
        match = cls.PATTERNS['url_format'].match(proxy_string)
        if match:
            protocol, host, port = match.groups()
            # Use default ports if not specified
            if not port:
                if protocol == 'http':
                    port = '80'
                elif protocol == 'https':
                    port = '443'
                elif protocol in ['socks4', 'socks5']:
                    port = '1080'
                else:
                    return None
            
            return {
                'protocol': protocol.lower(),
                'host': host,
                'port': port,
                'username': None,
                'password': None
            }
        
        return None
    
    @classmethod
    def normalize_proxy_string(cls, proxy_string: str, 
                              default_protocol: str = 'http') -> Optional[str]:
        """
        Normalize proxy string to standard format
        
        Args:
            proxy_string: Input proxy string
            default_protocol: Default protocol if none specified
            
        Returns:
            Normalized proxy string or None if invalid
        """
        parsed = cls.parse_proxy_string(proxy_string)
        if not parsed:
            return None
        
        protocol = parsed['protocol'] or default_protocol
        host = parsed['host']
        port = parsed['port']
        username = parsed['username']
        password = parsed['password']
        
        if username and password:
            return f"{protocol}://{username}:{password}@{host}:{port}"
        else:
            return f"{protocol}://{host}:{port}"


class ProxyValidator:
    """Comprehensive proxy validation with configurable rules"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize proxy validator
        
        Args:
            config: Validation configuration dictionary
        """
        self.config = config or {}
        self.rules = self._load_validation_rules()
        self.ip_validator = IPValidator()
        self.port_validator = PortValidator()
        self.format_parser = ProxyFormatParser()
    
    def _load_validation_rules(self) -> Dict[str, ValidationRule]:
        """Load validation rules from configuration"""
        default_rules = {
            'strict_ip_validation': ValidationRule(
                name='strict_ip_validation',
                enabled=self.config.get('strict_ip_validation', True)
            ),
            'allow_private_ips': ValidationRule(
                name='allow_private_ips',
                enabled=self.config.get('allow_private_ips', False)
            ),
            'allow_localhost': ValidationRule(
                name='allow_localhost',
                enabled=self.config.get('allow_localhost', False)
            ),
            'strict_port_validation': ValidationRule(
                name='strict_port_validation',
                enabled=self.config.get('strict_port_validation', False)
            ),
            'require_common_ports': ValidationRule(
                name='require_common_ports',
                enabled=self.config.get('require_common_ports', False)
            )
        }
        
        # Add custom rules from config
        custom_rules = self.config.get('custom_validation_rules', {})
        for rule_name, rule_config in custom_rules.items():
            default_rules[rule_name] = ValidationRule(
                name=rule_name,
                enabled=rule_config.get('enabled', True),
                strict=rule_config.get('strict', False),
                custom_params=rule_config.get('params', {})
            )
        
        return default_rules
    
    def validate_proxy_format(self, host: str, port: Union[int, str], 
                             protocol: str = 'http') -> bool:
        """
        Validate proxy format components
        
        Args:
            host: Proxy host (IP or hostname)
            port: Proxy port
            protocol: Proxy protocol
            
        Returns:
            True if valid proxy format
        """
        # Validate IP address
        allow_private = self.rules['allow_private_ips'].enabled
        allow_localhost = self.rules['allow_localhost'].enabled
        
        is_valid_ip, ip_version = self.ip_validator.validate_ip(
            host, allow_private, allow_localhost
        )
        
        if not is_valid_ip:
            # Try to resolve hostname
            if not self._validate_hostname(host):
                logger.debug(f"Invalid host: {host}")
                return False
        
        # Validate port
        strict_port = self.rules['strict_port_validation'].enabled
        if not self.port_validator.validate_port(port, protocol, strict_port):
            logger.debug(f"Invalid port: {port}")
            return False
        
        # Check if port is commonly used for proxies
        if self.rules['require_common_ports'].enabled:
            if not self.port_validator.is_common_proxy_port(port):
                logger.debug(f"Uncommon proxy port: {port}")
                return False
        
        return True
    
    def validate_proxy_string(self, proxy_string: str) -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        Validate complete proxy string
        
        Args:
            proxy_string: Proxy string to validate
            
        Returns:
            Tuple of (is_valid, parsed_components)
        """
        # Parse proxy string
        parsed = self.format_parser.parse_proxy_string(proxy_string)
        if not parsed:
            return False, None
        
        # Validate components
        is_valid = self.validate_proxy_format(
            parsed['host'], 
            parsed['port'], 
            parsed['protocol']
        )
        
        return is_valid, parsed if is_valid else None
    
    def _validate_hostname(self, hostname: str) -> bool:
        """Validate hostname format and resolution"""
        # Basic hostname format check
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$', hostname):
            return False
        
        # Try to resolve hostname (optional, can be slow)
        if self.rules.get('resolve_hostnames', ValidationRule(name='resolve_hostnames', enabled=False)).enabled:
            try:
                socket.gethostbyname(hostname)
                return True
            except socket.gaierror:
                return False
        
        return True
    
    def get_validation_errors(self, proxy_string: str) -> List[str]:
        """
        Get detailed validation errors for a proxy string
        
        Args:
            proxy_string: Proxy string to validate
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Parse proxy string
        parsed = self.format_parser.parse_proxy_string(proxy_string)
        if not parsed:
            errors.append("Invalid proxy string format")
            return errors
        
        host = parsed['host']
        port = parsed['port']
        protocol = parsed['protocol']
        
        # Validate IP/hostname
        allow_private = self.rules['allow_private_ips'].enabled
        allow_localhost = self.rules['allow_localhost'].enabled
        
        is_valid_ip, ip_version = self.ip_validator.validate_ip(
            host, allow_private, allow_localhost
        )
        
        if not is_valid_ip and not self._validate_hostname(host):
            errors.append(f"Invalid host: {host}")
        
        # Validate port
        try:
            port_num = int(port)
            if not (1 <= port_num <= 65535):
                errors.append(f"Port out of range: {port}")
        except ValueError:
            errors.append(f"Invalid port format: {port}")
        
        # Protocol-specific validation
        if protocol not in ['http', 'https', 'socks4', 'socks5']:
            errors.append(f"Unsupported protocol: {protocol}")
        
        return errors
    
    def update_rules(self, rule_updates: Dict[str, Dict[str, Any]]):
        """Update validation rules"""
        for rule_name, updates in rule_updates.items():
            if rule_name in self.rules:
                for key, value in updates.items():
                    setattr(self.rules[rule_name], key, value)
                logger.debug(f"Updated validation rule: {rule_name}")
    
    def get_rule_status(self) -> Dict[str, Dict[str, Any]]:
        """Get current status of all validation rules"""
        return {
            rule_name: {
                'enabled': rule.enabled,
                'strict': rule.strict,
                'custom_params': rule.custom_params
            }
            for rule_name, rule in self.rules.items()
        }
