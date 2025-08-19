"""
Migration utilities for HiberProxy Enhanced

Handles migration from legacy proxy.txt files to the new database format,
ensuring backward compatibility and data preservation.
"""

import re
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime

from ..core.database import DatabaseManager, ProxyModel, ProxySource
from ..core.validation import ProxyValidator

logger = logging.getLogger(__name__)


class ProxyMigrator:
    """Handles migration from legacy text files to database"""
    
    def __init__(self, db_manager: DatabaseManager, validator: Optional[ProxyValidator] = None):
        """
        Initialize migrator
        
        Args:
            db_manager: Database manager instance
            validator: Proxy validator instance (optional)
        """
        self.db_manager = db_manager
        self.validator = validator
        self.stats = {
            'total_processed': 0,
            'successful_imports': 0,
            'failed_imports': 0,
            'duplicates_skipped': 0,
            'invalid_proxies': 0
        }
    
    def migrate_from_text_file(self, file_path: str, default_protocol: str = "http") -> Dict[str, int]:
        """
        Migrate proxies from a text file to database
        
        Args:
            file_path: Path to the proxy text file
            default_protocol: Default protocol for proxies without explicit protocol
            
        Returns:
            Dictionary with migration statistics
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"Proxy file not found: {file_path}")
            return self.stats
        
        logger.info(f"Starting migration from {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            self._process_proxy_lines(lines, default_protocol)
            
            logger.info(f"Migration completed. Stats: {self.stats}")
            return self.stats
            
        except Exception as e:
            logger.error(f"Failed to migrate from {file_path}: {e}")
            return self.stats
    
    def migrate_multiple_files(self, file_paths: List[str], 
                              default_protocol: str = "http") -> Dict[str, int]:
        """
        Migrate proxies from multiple text files
        
        Args:
            file_paths: List of proxy file paths
            default_protocol: Default protocol for proxies
            
        Returns:
            Combined migration statistics
        """
        combined_stats = {
            'total_processed': 0,
            'successful_imports': 0,
            'failed_imports': 0,
            'duplicates_skipped': 0,
            'invalid_proxies': 0
        }
        
        for file_path in file_paths:
            file_stats = self.migrate_from_text_file(file_path, default_protocol)
            
            for key in combined_stats:
                combined_stats[key] += file_stats.get(key, 0)
        
        return combined_stats
    
    def _process_proxy_lines(self, lines: List[str], default_protocol: str):
        """Process individual proxy lines from text file"""
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            if not line or line.startswith('#'):
                continue
            
            self.stats['total_processed'] += 1
            
            try:
                proxy = self._parse_proxy_line(line, default_protocol)
                
                if proxy:
                    # Validate proxy if validator is available
                    if self.validator and not self.validator.validate_proxy_format(
                        proxy.host, proxy.port, proxy.protocol
                    ):
                        logger.warning(f"Invalid proxy format at line {line_num}: {line}")
                        self.stats['invalid_proxies'] += 1
                        continue
                    
                    # Try to add to database
                    try:
                        proxy_id = self.db_manager.add_proxy(proxy)
                        self.stats['successful_imports'] += 1
                        logger.debug(f"Imported proxy: {proxy.host}:{proxy.port}")
                        
                    except Exception as e:
                        if "UNIQUE constraint failed" in str(e):
                            self.stats['duplicates_skipped'] += 1
                            logger.debug(f"Duplicate proxy skipped: {proxy.host}:{proxy.port}")
                        else:
                            self.stats['failed_imports'] += 1
                            logger.error(f"Failed to import proxy at line {line_num}: {e}")
                else:
                    self.stats['invalid_proxies'] += 1
                    logger.warning(f"Could not parse proxy at line {line_num}: {line}")
                    
            except Exception as e:
                self.stats['failed_imports'] += 1
                logger.error(f"Error processing line {line_num}: {e}")
    
    def _parse_proxy_line(self, line: str, default_protocol: str) -> Optional[ProxyModel]:
        """
        Parse a single proxy line into ProxyModel
        
        Supports formats:
        - host:port
        - protocol://host:port
        - host:port:username:password
        - protocol://username:password@host:port
        """
        line = line.strip()
        
        # Pattern for protocol://username:password@host:port
        pattern1 = re.compile(r'^(https?|socks[45]?)://([^:]+):([^@]+)@([^:]+):(\d+)$')
        match = pattern1.match(line)
        if match:
            protocol, username, password, host, port = match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=protocol.lower(),
                username=username,
                password=password
            )
        
        # Pattern for protocol://host:port
        pattern2 = re.compile(r'^(https?|socks[45]?)://([^:]+):(\d+)$')
        match = pattern2.match(line)
        if match:
            protocol, host, port = match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=protocol.lower()
            )
        
        # Pattern for host:port:username:password
        pattern3 = re.compile(r'^([^:]+):(\d+):([^:]+):(.+)$')
        match = pattern3.match(line)
        if match:
            host, port, username, password = match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=default_protocol,
                username=username,
                password=password
            )
        
        # Pattern for host:port
        pattern4 = re.compile(r'^([^:]+):(\d+)$')
        match = pattern4.match(line)
        if match:
            host, port = match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=default_protocol
            )
        
        return None
    
    def export_to_text_file(self, output_path: str, protocol: Optional[str] = None,
                           working_only: bool = True, include_auth: bool = False) -> int:
        """
        Export proxies from database to text file
        
        Args:
            output_path: Path for output file
            protocol: Filter by protocol (optional)
            working_only: Only export working proxies
            include_auth: Include authentication in output
            
        Returns:
            Number of proxies exported
        """
        proxies = self.db_manager.get_proxies(protocol=protocol, working_only=working_only)
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        exported_count = 0
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Exported from HiberProxy Enhanced on {datetime.now().isoformat()}\n")
            f.write(f"# Total proxies: {len(proxies)}\n")
            f.write(f"# Protocol filter: {protocol or 'all'}\n")
            f.write(f"# Working only: {working_only}\n\n")
            
            for proxy in proxies:
                if include_auth and proxy.username and proxy.password:
                    line = f"{proxy.protocol}://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}\n"
                else:
                    line = f"{proxy.protocol}://{proxy.host}:{proxy.port}\n"
                
                f.write(line)
                exported_count += 1
        
        logger.info(f"Exported {exported_count} proxies to {output_path}")
        return exported_count
    
    def create_default_sources(self):
        """Create default proxy sources in database"""
        default_sources = [
            ProxySource(
                url="http://free-proxy-list.net/",
                name="Free Proxy List",
                is_active=True,
                scrape_interval=3600
            ),
            ProxySource(
                url="https://www.us-proxy.org/",
                name="US Proxy",
                is_active=True,
                scrape_interval=3600
            ),
            ProxySource(
                url="https://www.socks-proxy.net/",
                name="SOCKS Proxy",
                is_active=True,
                scrape_interval=3600
            ),
            ProxySource(
                url="https://www.proxy-list.download/api/v1/get?type=http",
                name="Proxy List Download HTTP",
                is_active=True,
                scrape_interval=1800
            ),
            ProxySource(
                url="https://www.proxy-list.download/api/v1/get?type=socks4",
                name="Proxy List Download SOCKS4",
                is_active=True,
                scrape_interval=1800
            ),
            ProxySource(
                url="https://www.proxy-list.download/api/v1/get?type=socks5",
                name="Proxy List Download SOCKS5",
                is_active=True,
                scrape_interval=1800
            )
        ]
        
        created_count = 0
        for source in default_sources:
            try:
                self.db_manager.add_proxy_source(source)
                created_count += 1
                logger.debug(f"Created default source: {source.name}")
            except Exception as e:
                logger.debug(f"Source already exists: {source.name}")
        
        logger.info(f"Created {created_count} default proxy sources")
        return created_count
    
    def get_migration_stats(self) -> Dict[str, Any]:
        """Get detailed migration statistics"""
        return {
            **self.stats,
            'success_rate': (
                self.stats['successful_imports'] / self.stats['total_processed'] * 100
                if self.stats['total_processed'] > 0 else 0
            ),
            'database_stats': self.db_manager.get_database_stats()
        }
