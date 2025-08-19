"""
Logging configuration for HiberProxy Enhanced

Provides structured logging with multiple handlers, formatters, and configurable levels.
Replaces all print statements with proper logging calls.
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
            
        # Add extra fields if present
        if hasattr(record, 'proxy_id'):
            log_entry['proxy_id'] = record.proxy_id
        if hasattr(record, 'protocol'):
            log_entry['protocol'] = record.protocol
        if hasattr(record, 'response_time'):
            log_entry['response_time'] = record.response_time
            
        return json.dumps(log_entry)


class ColoredConsoleFormatter(logging.Formatter):
    """Colored console formatter for better readability"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors"""
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        
        # Format message
        message = super().format(record)
        
        return f"{color}[{timestamp}] {record.levelname:8} {reset}{message}"


def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[str] = None,
    enable_console: bool = True,
    enable_file: bool = True,
    enable_json: bool = False,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> Dict[str, logging.Logger]:
    """
    Set up comprehensive logging system
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files (default: ./logs)
        enable_console: Enable console logging
        enable_file: Enable file logging
        enable_json: Enable JSON structured logging
        max_file_size: Maximum size for log files before rotation
        backup_count: Number of backup files to keep
        
    Returns:
        Dictionary of configured loggers
    """
    # Set up log directory
    if log_dir is None:
        log_dir = Path.cwd() / "logs"
    else:
        log_dir = Path(log_dir)
    
    log_dir.mkdir(exist_ok=True)
    
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Create loggers for different components
    loggers = {
        'main': logging.getLogger('hiber_proxy.main'),
        'database': logging.getLogger('hiber_proxy.database'),
        'scraper': logging.getLogger('hiber_proxy.scraper'),
        'checker': logging.getLogger('hiber_proxy.checker'),
        'validator': logging.getLogger('hiber_proxy.validator'),
        'protocol': logging.getLogger('hiber_proxy.protocol')
    }
    
    # Set up console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_formatter = ColoredConsoleFormatter(
            '%(name)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # Set up file handlers
    if enable_file:
        # Main log file
        main_file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "hiber_proxy.log",
            maxBytes=max_file_size,
            backupCount=backup_count
        )
        main_file_handler.setLevel(numeric_level)
        
        if enable_json:
            main_file_formatter = JSONFormatter()
        else:
            main_file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        
        main_file_handler.setFormatter(main_file_formatter)
        root_logger.addHandler(main_file_handler)
        
        # Error log file (ERROR and CRITICAL only)
        error_file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "errors.log",
            maxBytes=max_file_size,
            backupCount=backup_count
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(main_file_formatter)
        root_logger.addHandler(error_file_handler)
    
    # Log startup message
    main_logger = loggers['main']
    main_logger.info("HiberProxy Enhanced logging system initialized")
    main_logger.info(f"Log level: {log_level}")
    main_logger.info(f"Log directory: {log_dir}")
    main_logger.info(f"Console logging: {enable_console}")
    main_logger.info(f"File logging: {enable_file}")
    main_logger.info(f"JSON logging: {enable_json}")
    
    return loggers


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific component"""
    return logging.getLogger(f'hiber_proxy.{name}')


def log_proxy_check(logger: logging.Logger, proxy_id: str, protocol: str, 
                   success: bool, response_time: Optional[float] = None, 
                   error: Optional[str] = None):
    """Log proxy check results with structured data"""
    extra = {
        'proxy_id': proxy_id,
        'protocol': protocol,
        'response_time': response_time
    }
    
    if success:
        logger.info(f"Proxy check successful: {proxy_id}", extra=extra)
    else:
        logger.warning(f"Proxy check failed: {proxy_id} - {error}", extra=extra)


def log_proxy_scrape(logger: logging.Logger, source_url: str, 
                    proxies_found: int, success: bool, 
                    error: Optional[str] = None):
    """Log proxy scraping results"""
    extra = {
        'source_url': source_url,
        'proxies_found': proxies_found
    }
    
    if success:
        logger.info(f"Scraped {proxies_found} proxies from {source_url}", extra=extra)
    else:
        logger.error(f"Failed to scrape from {source_url}: {error}", extra=extra)
