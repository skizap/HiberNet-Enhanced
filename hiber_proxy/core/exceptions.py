"""
Custom exception types for HiberProxy Enhanced

Provides specific exception classes for different error scenarios with
recovery mechanisms and detailed error information.
"""

from typing import Optional, Dict, Any, List
from enum import Enum


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification"""
    NETWORK = "network"
    VALIDATION = "validation"
    DATABASE = "database"
    PROTOCOL = "protocol"
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    PARSING = "parsing"
    RESOURCE = "resource"


class HiberProxyError(Exception):
    """Base exception class for HiberProxy Enhanced"""
    
    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.NETWORK,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM, 
                 details: Optional[Dict[str, Any]] = None,
                 recoverable: bool = True, recovery_suggestions: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.details = details or {}
        self.recoverable = recoverable
        self.recovery_suggestions = recovery_suggestions or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization"""
        return {
            'type': self.__class__.__name__,
            'message': self.message,
            'category': self.category.value,
            'severity': self.severity.value,
            'details': self.details,
            'recoverable': self.recoverable,
            'recovery_suggestions': self.recovery_suggestions
        }


class ProxyValidationError(HiberProxyError):
    """Raised when proxy validation fails"""
    
    def __init__(self, message: str, proxy_string: str, validation_errors: List[str],
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            details={
                'proxy_string': proxy_string,
                'validation_errors': validation_errors,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check proxy format (IP:PORT or protocol://IP:PORT)",
                "Verify IP address is valid",
                "Ensure port is in valid range (1-65535)",
                "Check if protocol is supported (http/https/socks4/socks5)"
            ]
        )
        self.proxy_string = proxy_string
        self.validation_errors = validation_errors


class ProxyConnectionError(HiberProxyError):
    """Raised when proxy connection fails"""
    
    def __init__(self, message: str, host: str, port: int, protocol: str,
                 timeout: Optional[float] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            details={
                'host': host,
                'port': port,
                'protocol': protocol,
                'timeout': timeout,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check if proxy server is running",
                "Verify network connectivity",
                "Try increasing timeout value",
                "Check firewall settings",
                "Verify proxy credentials if required"
            ]
        )
        self.host = host
        self.port = port
        self.protocol = protocol


class ProxyAuthenticationError(HiberProxyError):
    """Raised when proxy authentication fails"""
    
    def __init__(self, message: str, host: str, port: int, username: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.MEDIUM,
            details={
                'host': host,
                'port': port,
                'username': username,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Verify username and password are correct",
                "Check if proxy requires authentication",
                "Try without authentication if optional",
                "Contact proxy provider for credentials"
            ]
        )
        self.host = host
        self.port = port
        self.username = username


class DatabaseError(HiberProxyError):
    """Raised when database operations fail"""
    
    def __init__(self, message: str, operation: str, table: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            details={
                'operation': operation,
                'table': table,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check database file permissions",
                "Verify database is not corrupted",
                "Try restarting the application",
                "Check available disk space",
                "Run database integrity check"
            ]
        )
        self.operation = operation
        self.table = table


class ConfigurationError(HiberProxyError):
    """Raised when configuration is invalid or missing"""
    
    def __init__(self, message: str, config_key: Optional[str] = None,
                 config_file: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH,
            details={
                'config_key': config_key,
                'config_file': config_file,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check configuration file syntax",
                "Verify all required settings are present",
                "Use default configuration as reference",
                "Check file permissions",
                "Validate configuration values"
            ]
        )
        self.config_key = config_key
        self.config_file = config_file


class ProtocolError(HiberProxyError):
    """Raised when protocol-specific operations fail"""
    
    def __init__(self, message: str, protocol: str, operation: str,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.PROTOCOL,
            severity=ErrorSeverity.MEDIUM,
            details={
                'protocol': protocol,
                'operation': operation,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                f"Verify {protocol.upper()} protocol is supported",
                "Check protocol-specific configuration",
                "Try with different protocol",
                "Verify proxy supports the protocol"
            ]
        )
        self.protocol = protocol
        self.operation = operation


class ParsingError(HiberProxyError):
    """Raised when parsing operations fail"""
    
    def __init__(self, message: str, data_type: str, data_source: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.PARSING,
            severity=ErrorSeverity.LOW,
            details={
                'data_type': data_type,
                'data_source': data_source,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check data format is correct",
                "Verify data source is accessible",
                "Try with different parser",
                "Check for encoding issues"
            ]
        )
        self.data_type = data_type
        self.data_source = data_source


class ResourceError(HiberProxyError):
    """Raised when resource operations fail"""
    
    def __init__(self, message: str, resource_type: str, resource_path: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            details={
                'resource_type': resource_type,
                'resource_path': resource_path,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check file/resource exists",
                "Verify permissions",
                "Check available disk space",
                "Try with different path"
            ]
        )
        self.resource_type = resource_type
        self.resource_path = resource_path


class ScrapingError(HiberProxyError):
    """Raised when web scraping operations fail"""
    
    def __init__(self, message: str, url: str, status_code: Optional[int] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.LOW,
            details={
                'url': url,
                'status_code': status_code,
                **(details or {})
            },
            recoverable=True,
            recovery_suggestions=[
                "Check if URL is accessible",
                "Verify internet connection",
                "Try again later (rate limiting)",
                "Check if website structure changed",
                "Use different user agent"
            ]
        )
        self.url = url
        self.status_code = status_code


# Exception mapping for common Python exceptions
EXCEPTION_MAPPING = {
    ConnectionError: ProxyConnectionError,
    TimeoutError: ProxyConnectionError,
    ValueError: ProxyValidationError,
    FileNotFoundError: ResourceError,
    PermissionError: ResourceError,
}


def wrap_exception(func):
    """Decorator to wrap common exceptions with HiberProxy exceptions"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HiberProxyError:
            # Re-raise HiberProxy exceptions as-is
            raise
        except Exception as e:
            # Map common exceptions to HiberProxy exceptions
            exception_class = EXCEPTION_MAPPING.get(type(e), HiberProxyError)
            
            if exception_class == ProxyConnectionError:
                raise ProxyConnectionError(
                    message=str(e),
                    host="unknown",
                    port=0,
                    protocol="unknown",
                    details={'original_exception': str(e)}
                )
            elif exception_class == ResourceError:
                raise ResourceError(
                    message=str(e),
                    resource_type="file",
                    details={'original_exception': str(e)}
                )
            else:
                raise HiberProxyError(
                    message=str(e),
                    details={'original_exception': str(e)}
                )
    
    return wrapper
