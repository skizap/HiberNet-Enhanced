"""
Configuration management for HiberProxy Enhanced

Handles loading and managing configuration from files, environment variables,
and command-line arguments with proper defaults and validation.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    path: str = "hiber_proxy.db"
    connection_pool_size: int = 10
    timeout: int = 30
    backup_enabled: bool = True
    backup_interval: int = 3600  # seconds


@dataclass
class LoggingConfig:
    """Logging configuration settings"""
    level: str = "INFO"
    log_dir: str = "logs"
    enable_console: bool = True
    enable_file: bool = True
    enable_json: bool = False
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


@dataclass
class ScrapingConfig:
    """Proxy scraping configuration"""
    request_timeout: int = 30
    retry_attempts: int = 3
    retry_delay_base: float = 2.0
    max_retry_delay: float = 60.0
    request_delay_min: float = 2.0
    request_delay_max: float = 5.0
    concurrent_downloads: int = 3
    user_agent_rotation: bool = True
    respect_rate_limits: bool = True
    validate_before_import: bool = True
    enabled_repositories: list = None
    disabled_sources: list = None

    def __post_init__(self):
        if self.enabled_repositories is None:
            self.enabled_repositories = ['thespeedx', 'monosans', 'databay-labs', 'zloi-user']
        if self.disabled_sources is None:
            self.disabled_sources = []


@dataclass
class CheckingConfig:
    """Proxy checking configuration"""
    timeout: int = 60
    test_url: str = "http://www.google.com"
    concurrent_checks: int = 50
    max_failures: int = 5
    recheck_interval: int = 3600  # seconds
    protocols_to_check: list = None
    
    def __post_init__(self):
        if self.protocols_to_check is None:
            self.protocols_to_check = ["http", "https", "socks4", "socks5"]


@dataclass
class ValidationConfig:
    """Validation configuration"""
    strict_ip_validation: bool = True
    allow_private_ips: bool = False
    allow_localhost: bool = False
    port_range_min: int = 1
    port_range_max: int = 65535
    custom_validation_rules: dict = None
    
    def __post_init__(self):
        if self.custom_validation_rules is None:
            self.custom_validation_rules = {}


@dataclass
class ProxySourceConfig:
    """Proxy source configuration"""
    enabled_sources: list = None
    custom_sources: list = None
    source_priorities: dict = None
    
    def __post_init__(self):
        if self.enabled_sources is None:
            self.enabled_sources = ["free-proxy-list", "proxy-list", "blogspot"]
        if self.custom_sources is None:
            self.custom_sources = []
        if self.source_priorities is None:
            self.source_priorities = {}


@dataclass
class MemoryConfig:
    """Memory management configuration"""
    max_memory_mb: int = 512  # Maximum memory usage in MB
    batch_size: int = 1000    # Default batch size for processing
    cache_size: int = 10000   # Maximum items in cache
    gc_threshold: float = 0.8 # Trigger GC when memory usage exceeds this ratio
    enable_monitoring: bool = True
    cleanup_interval: int = 300  # Cleanup interval in seconds
    streaming_enabled: bool = True  # Enable streaming processing


@dataclass
class TimeoutConfig:
    """Configurable timeout settings for different operations"""
    connection_timeout: int = 30      # Basic connection timeout
    read_timeout: int = 60           # Read operation timeout
    write_timeout: int = 30          # Write operation timeout
    scraping_timeout: int = 45       # Web scraping timeout
    database_timeout: int = 30       # Database operation timeout
    health_check_timeout: int = 15   # Proxy health check timeout
    bulk_operation_timeout: int = 300 # Bulk operations timeout


@dataclass
class ProxyListConfig:
    """Multiple proxy list management configuration"""
    default_list_name: str = "default"
    max_lists: int = 10
    list_storage_path: str = "proxy_lists"
    auto_backup: bool = True
    backup_interval: int = 3600  # seconds
    cross_list_deduplication: bool = True


@dataclass
class AppConfig:
    """Main application configuration"""
    database: DatabaseConfig = None
    logging: LoggingConfig = None
    scraping: ScrapingConfig = None
    checking: CheckingConfig = None
    validation: ValidationConfig = None
    proxy_sources: ProxySourceConfig = None
    memory: MemoryConfig = None
    timeouts: TimeoutConfig = None
    proxy_lists: ProxyListConfig = None
    
    def __post_init__(self):
        if self.database is None:
            self.database = DatabaseConfig()
        if self.logging is None:
            self.logging = LoggingConfig()
        if self.scraping is None:
            self.scraping = ScrapingConfig()
        if self.checking is None:
            self.checking = CheckingConfig()
        if self.validation is None:
            self.validation = ValidationConfig()
        if self.proxy_sources is None:
            self.proxy_sources = ProxySourceConfig()
        if self.memory is None:
            self.memory = MemoryConfig()
        if self.timeouts is None:
            self.timeouts = TimeoutConfig()
        if self.proxy_lists is None:
            self.proxy_lists = ProxyListConfig()


class ConfigManager:
    """Configuration manager with support for files, environment variables, and defaults"""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """
        Initialize configuration manager
        
        Args:
            config_path: Path to configuration file (JSON or YAML)
        """
        self.config_path = Path(config_path) if config_path else None
        self.config = AppConfig()
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file and environment variables"""
        # Load from file if specified
        if self.config_path and self.config_path.exists():
            try:
                self._load_from_file()
                logger.info(f"Configuration loaded from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config from {self.config_path}: {e}")
                logger.info("Using default configuration")
        
        # Override with environment variables
        self._load_from_env()
        
        logger.debug("Configuration loaded successfully")
    
    def _load_from_file(self):
        """Load configuration from JSON or YAML file"""
        if not self.config_path.exists():
            return
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            if self.config_path.suffix.lower() in ['.yaml', '.yml']:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        # Update configuration with file data
        self._update_config_from_dict(data)
    
    def _load_from_env(self):
        """Load configuration from environment variables"""
        env_mappings = {
            'HIBER_DB_PATH': ('database', 'path'),
            'HIBER_LOG_LEVEL': ('logging', 'level'),
            'HIBER_LOG_DIR': ('logging', 'log_dir'),
            'HIBER_SCRAPE_TIMEOUT': ('scraping', 'timeout'),
            'HIBER_CHECK_TIMEOUT': ('checking', 'timeout'),
            'HIBER_CHECK_URL': ('checking', 'test_url'),
            'HIBER_CONCURRENT_CHECKS': ('checking', 'concurrent_checks'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert string values to appropriate types
                if key in ['timeout', 'concurrent_checks', 'max_retries', 'backup_count']:
                    value = int(value)
                elif key in ['enable_console', 'enable_file', 'enable_json', 'strict_ip_validation']:
                    value = value.lower() in ['true', '1', 'yes', 'on']
                
                # Set the value in config
                section_obj = getattr(self.config, section)
                setattr(section_obj, key, value)
    
    def _update_config_from_dict(self, data: Dict[str, Any]):
        """Update configuration from dictionary"""
        for section_name, section_data in data.items():
            if hasattr(self.config, section_name) and isinstance(section_data, dict):
                section_obj = getattr(self.config, section_name)
                for key, value in section_data.items():
                    if hasattr(section_obj, key):
                        setattr(section_obj, key, value)
    
    def save_config(self, path: Optional[Union[str, Path]] = None):
        """Save current configuration to file"""
        save_path = Path(path) if path else self.config_path
        if not save_path:
            raise ValueError("No save path specified")
        
        config_dict = asdict(self.config)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            if save_path.suffix.lower() in ['.yaml', '.yml']:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                json.dump(config_dict, f, indent=2)
        
        logger.info(f"Configuration saved to {save_path}")
    
    def get_database_config(self) -> DatabaseConfig:
        """Get database configuration"""
        return self.config.database
    
    def get_logging_config(self) -> LoggingConfig:
        """Get logging configuration"""
        return self.config.logging
    
    def get_scraping_config(self) -> ScrapingConfig:
        """Get scraping configuration"""
        return self.config.scraping
    
    def get_checking_config(self) -> CheckingConfig:
        """Get checking configuration"""
        return self.config.checking
    
    def get_validation_config(self) -> ValidationConfig:
        """Get validation configuration"""
        return self.config.validation
    
    def get_proxy_sources_config(self) -> ProxySourceConfig:
        """Get proxy sources configuration"""
        return self.config.proxy_sources

    def get_memory_config(self) -> MemoryConfig:
        """Get memory management configuration"""
        return self.config.memory

    def get_timeout_config(self) -> TimeoutConfig:
        """Get timeout configuration"""
        return self.config.timeouts

    def get_proxy_lists_config(self) -> ProxyListConfig:
        """Get proxy lists configuration"""
        return self.config.proxy_lists
    
    def update_config(self, section: str, **kwargs):
        """Update configuration section with new values"""
        if hasattr(self.config, section):
            section_obj = getattr(self.config, section)
            for key, value in kwargs.items():
                if hasattr(section_obj, key):
                    setattr(section_obj, key, value)
                    logger.debug(f"Updated {section}.{key} = {value}")
        else:
            logger.warning(f"Unknown configuration section: {section}")
    
    def create_default_config_file(self, path: Union[str, Path]):
        """Create a default configuration file"""
        config_path = Path(path)
        default_config = AppConfig()
        
        config_dict = asdict(default_config)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            if config_path.suffix.lower() in ['.yaml', '.yml']:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                json.dump(config_dict, f, indent=2)
        
        logger.info(f"Default configuration file created at {config_path}")
        return config_path
