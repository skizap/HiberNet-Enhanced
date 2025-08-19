"""
HiberProxy Enhanced - Multi-Protocol Proxy Management System

A comprehensive proxy management system supporting HTTP, HTTPS, SOCKS4, and SOCKS5 protocols
with database integration, advanced validation, and intelligent analytics.
"""

__version__ = "2.0.0"
__author__ = "HiberProxy Enhanced Team"
__description__ = "Multi-Protocol Proxy Management System"

from .core.database import DatabaseManager, ProxyModel
from .core.logging_config import setup_logging
from .core.validation import ProxyValidator
from .core.protocols import ProtocolDetector, ProxyChecker
from .utils.config import ConfigManager

__all__ = [
    'DatabaseManager',
    'ProxyModel', 
    'setup_logging',
    'ProxyValidator',
    'ProtocolDetector',
    'ProxyChecker',
    'ConfigManager'
]
