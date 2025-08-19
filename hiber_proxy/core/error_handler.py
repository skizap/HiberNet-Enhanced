"""
Error handling utilities for HiberProxy Enhanced

Provides centralized error handling, recovery mechanisms, and error reporting.
"""

import logging
import traceback
from typing import Optional, Dict, Any, List, Callable, Union
from contextlib import contextmanager
from functools import wraps

from .exceptions import (
    HiberProxyError, ErrorSeverity, ErrorCategory,
    ProxyValidationError, ProxyConnectionError, DatabaseError,
    ConfigurationError, ProtocolError, ParsingError, ResourceError
)

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Centralized error handler with recovery mechanisms"""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.error_stats = {
            'total_errors': 0,
            'by_category': {},
            'by_severity': {},
            'recoverable_errors': 0,
            'unrecoverable_errors': 0
        }
    
    def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Handle an error with appropriate logging and recovery
        
        Args:
            error: The exception to handle
            context: Additional context information
            
        Returns:
            True if error was handled and recovery is possible, False otherwise
        """
        # Convert to HiberProxyError if needed
        if not isinstance(error, HiberProxyError):
            error = self._convert_to_hiber_error(error)
        
        # Update statistics
        self._update_error_stats(error)
        
        # Log the error
        self._log_error(error, context)
        
        # Attempt recovery if possible
        if error.recoverable:
            return self._attempt_recovery(error, context)
        
        return False
    
    def _convert_to_hiber_error(self, error: Exception) -> HiberProxyError:
        """Convert standard exceptions to HiberProxyError"""
        error_message = str(error)
        
        if isinstance(error, ConnectionError):
            return ProxyConnectionError(
                message=error_message,
                host="unknown",
                port=0,
                protocol="unknown",
                details={'original_exception': type(error).__name__}
            )
        elif isinstance(error, ValueError):
            return ProxyValidationError(
                message=error_message,
                proxy_string="unknown",
                validation_errors=[error_message]
            )
        elif isinstance(error, FileNotFoundError):
            return ResourceError(
                message=error_message,
                resource_type="file",
                details={'original_exception': type(error).__name__}
            )
        else:
            return HiberProxyError(
                message=error_message,
                details={'original_exception': type(error).__name__}
            )
    
    def _update_error_stats(self, error: HiberProxyError):
        """Update error statistics"""
        self.error_stats['total_errors'] += 1
        
        # By category
        category = error.category.value
        self.error_stats['by_category'][category] = self.error_stats['by_category'].get(category, 0) + 1
        
        # By severity
        severity = error.severity.value
        self.error_stats['by_severity'][severity] = self.error_stats['by_severity'].get(severity, 0) + 1
        
        # Recoverable vs unrecoverable
        if error.recoverable:
            self.error_stats['recoverable_errors'] += 1
        else:
            self.error_stats['unrecoverable_errors'] += 1
    
    def _log_error(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None):
        """Log error with appropriate level based on severity"""
        log_data = {
            'error': error.to_dict(),
            'context': context or {}
        }
        
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(f"Critical error: {error.message}", extra=log_data)
        elif error.severity == ErrorSeverity.HIGH:
            logger.error(f"High severity error: {error.message}", extra=log_data)
        elif error.severity == ErrorSeverity.MEDIUM:
            logger.warning(f"Medium severity error: {error.message}", extra=log_data)
        else:
            logger.info(f"Low severity error: {error.message}", extra=log_data)
    
    def _attempt_recovery(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None) -> bool:
        """Attempt to recover from error"""
        logger.debug(f"Attempting recovery for {error.__class__.__name__}: {error.message}")
        
        # Category-specific recovery strategies
        if error.category == ErrorCategory.NETWORK:
            return self._recover_network_error(error, context)
        elif error.category == ErrorCategory.DATABASE:
            return self._recover_database_error(error, context)
        elif error.category == ErrorCategory.CONFIGURATION:
            return self._recover_configuration_error(error, context)
        elif error.category == ErrorCategory.VALIDATION:
            return self._recover_validation_error(error, context)
        
        return False
    
    def _recover_network_error(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None) -> bool:
        """Attempt to recover from network errors"""
        # For network errors, we can suggest retrying with different parameters
        logger.debug("Network error recovery: suggesting retry with increased timeout")
        return True  # Indicate that retry is possible
    
    def _recover_database_error(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None) -> bool:
        """Attempt to recover from database errors"""
        # For database errors, we might try to reconnect or use backup
        logger.debug("Database error recovery: suggesting database reconnection")
        return True
    
    def _recover_configuration_error(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None) -> bool:
        """Attempt to recover from configuration errors"""
        # For config errors, we might use defaults
        logger.debug("Configuration error recovery: suggesting default configuration")
        return True
    
    def _recover_validation_error(self, error: HiberProxyError, context: Optional[Dict[str, Any]] = None) -> bool:
        """Attempt to recover from validation errors"""
        # For validation errors, recovery usually means skipping the invalid item
        logger.debug("Validation error recovery: suggesting skip invalid item")
        return True
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        return self.error_stats.copy()
    
    def reset_stats(self):
        """Reset error statistics"""
        self.error_stats = {
            'total_errors': 0,
            'by_category': {},
            'by_severity': {},
            'recoverable_errors': 0,
            'unrecoverable_errors': 0
        }


# Global error handler instance
_error_handler = ErrorHandler()


def get_error_handler() -> ErrorHandler:
    """Get the global error handler instance"""
    return _error_handler


@contextmanager
def error_context(operation: str, **context_data):
    """Context manager for error handling"""
    try:
        yield
    except Exception as e:
        context = {
            'operation': operation,
            **context_data
        }
        handled = _error_handler.handle_error(e, context)
        # For proxy connection operations, let the decorator handle the error
        if 'proxy_connection' in operation.lower() or 'connectivity' in operation.lower():
            raise  # Let the decorator handle it
        elif not handled:
            raise


def handle_errors(operation: str = None, max_retries: int = None,
                 retry_delay: float = None, reraise: bool = True, default_return=None):
    """Decorator for automatic error handling"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = max_retries or _error_handler.max_retries
            delay = retry_delay or _error_handler.retry_delay
            op_name = operation or f"{func.__module__}.{func.__name__}"

            last_exception = None

            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    context = {
                        'operation': op_name,
                        'attempt': attempt + 1,
                        'max_retries': retries,
                        'function': func.__name__,
                        'args': str(args)[:100],  # Truncate for logging
                        'kwargs': str(kwargs)[:100]
                    }

                    handled = _error_handler.handle_error(e, context)

                    if attempt < retries and handled:
                        logger.info(f"Retrying {op_name} (attempt {attempt + 2}/{retries + 1})")
                        import time
                        time.sleep(delay)
                        continue
                    else:
                        if reraise:
                            raise
                        else:
                            # Return a proper default value instead of None
                            if default_return is not None:
                                return default_return
                            # For proxy check functions, return a failed ProxyCheckResult
                            if ('check_connectivity' in func.__name__ or 'check_proxy' in func.__name__ or
                                'proxy_check' in op_name.lower() or 'connectivity' in op_name.lower()):
                                try:
                                    from .protocols import ProxyCheckResult
                                    return ProxyCheckResult(
                                        success=False,
                                        error_message=f"Failed after {retries + 1} attempts: {str(last_exception)}"
                                    )
                                except ImportError:
                                    # Fallback if import fails
                                    pass
                            return None

            # If we get here, all retries failed
            if reraise and last_exception:
                raise last_exception

            # Return appropriate default for failed operations
            if default_return is not None:
                return default_return
            if ('check_connectivity' in func.__name__ or 'check_proxy' in func.__name__ or
                'proxy_check' in op_name.lower() or 'connectivity' in op_name.lower()):
                try:
                    from .protocols import ProxyCheckResult
                    return ProxyCheckResult(
                        success=False,
                        error_message=f"Failed after {retries + 1} attempts: {str(last_exception) if last_exception else 'Unknown error'}"
                    )
                except ImportError:
                    # Fallback if import fails
                    pass
            return None

        return wrapper
    return decorator


def safe_execute(func: Callable, *args, default=None, **kwargs):
    """Safely execute a function with error handling"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        _error_handler.handle_error(e, {
            'function': func.__name__,
            'args': str(args)[:100],
            'kwargs': str(kwargs)[:100]
        })
        return default


def format_error_for_user(error: Exception) -> str:
    """Format error message for user display"""
    if isinstance(error, HiberProxyError):
        message = f"Error: {error.message}"
        if error.recovery_suggestions:
            message += "\n\nSuggestions:"
            for suggestion in error.recovery_suggestions:
                message += f"\n  • {suggestion}"
        return message
    else:
        return f"Unexpected error: {str(error)}"


def log_error_summary():
    """Log a summary of all errors encountered"""
    stats = _error_handler.get_error_stats()
    
    if stats['total_errors'] == 0:
        logger.info("No errors encountered")
        return
    
    logger.info(f"Error Summary: {stats['total_errors']} total errors")
    logger.info(f"  Recoverable: {stats['recoverable_errors']}")
    logger.info(f"  Unrecoverable: {stats['unrecoverable_errors']}")
    
    if stats['by_category']:
        logger.info("  By Category:")
        for category, count in stats['by_category'].items():
            logger.info(f"    {category}: {count}")
    
    if stats['by_severity']:
        logger.info("  By Severity:")
        for severity, count in stats['by_severity'].items():
            logger.info(f"    {severity}: {count}")
