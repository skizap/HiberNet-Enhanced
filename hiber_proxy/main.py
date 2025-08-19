"""
Main application entry point for HiberProxy Enhanced

Provides command-line interface and integrates all components for
comprehensive proxy management with multi-protocol support.
"""

import argparse
import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging

# Add the parent directory to the path so we can import hiber_proxy modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hiber_proxy.core.logging_config import setup_logging, get_logger
from hiber_proxy.core.database import DatabaseManager, ProxyModel
from hiber_proxy.core.validation import ProxyValidator
from hiber_proxy.core.protocols import ProtocolDetector, ProxyChecker, ProxyProtocol
from hiber_proxy.core.memory_manager import get_memory_manager, MemoryConfig
from hiber_proxy.core.proxy_lists import ProxyListManager
from hiber_proxy.utils.config import ConfigManager
from hiber_proxy.utils.migration import ProxyMigrator
from hiber_proxy.utils.exporters import ExportManager
from hiber_proxy.scrapers.github_scrapers import GitHubProxyScrapers, ScrapingConfig


class HiberProxyApp:
    """Main application class for HiberProxy Enhanced"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize HiberProxy application
        
        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config_manager = ConfigManager(config_path)
        
        # Set up logging
        log_config = self.config_manager.get_logging_config()
        self.loggers = setup_logging(
            log_level=log_config.level,
            log_dir=log_config.log_dir,
            enable_console=log_config.enable_console,
            enable_file=log_config.enable_file,
            enable_json=log_config.enable_json,
            max_file_size=log_config.max_file_size,
            backup_count=log_config.backup_count
        )
        
        self.logger = get_logger('main')
        self.logger.info("HiberProxy Enhanced starting up...")
        
        # Initialize components
        db_config = self.config_manager.get_database_config()
        timeout_config = self.config_manager.get_timeout_config()
        self.db_manager = DatabaseManager(
            db_path=db_config.path,
            pool_size=db_config.connection_pool_size,
            timeout=timeout_config.database_timeout
        )
        
        validation_config = self.config_manager.get_validation_config()
        self.validator = ProxyValidator(validation_config.__dict__)
        
        checking_config = self.config_manager.get_checking_config()
        self.proxy_checker = ProxyChecker(
            timeout=timeout_config.health_check_timeout,
            max_concurrent=checking_config.concurrent_checks
        )
        
        self.migrator = ProxyMigrator(self.db_manager, self.validator)

        # Initialize memory management
        memory_config = self.config_manager.get_memory_config()
        self.memory_manager = get_memory_manager(memory_config)

        # Initialize proxy list manager
        proxy_lists_config = self.config_manager.get_proxy_lists_config()
        self.proxy_list_manager = ProxyListManager(self.db_manager, proxy_lists_config)

        # Initialize scrapers with timeout configuration
        scraping_config_obj = self.config_manager.get_scraping_config()
        scraping_config = ScrapingConfig(
            request_timeout=timeout_config.scraping_timeout,  # Use timeout config
            retry_attempts=scraping_config_obj.retry_attempts,
            retry_delay_base=scraping_config_obj.retry_delay_base,
            max_retry_delay=scraping_config_obj.max_retry_delay,
            request_delay_min=scraping_config_obj.request_delay_min,
            request_delay_max=scraping_config_obj.request_delay_max,
            concurrent_downloads=scraping_config_obj.concurrent_downloads,
            user_agent_rotation=scraping_config_obj.user_agent_rotation,
            respect_rate_limits=scraping_config_obj.respect_rate_limits,
            validate_before_import=scraping_config_obj.validate_before_import
        )
        self.scrapers = GitHubProxyScrapers(
            db_manager=self.db_manager,
            validator=self.validator,
            config=scraping_config
        )

        # Initialize export manager
        self.export_manager = ExportManager()

        self.logger.info("HiberProxy Enhanced initialized successfully")
    
    def migrate_legacy_files(self, file_paths: List[str], default_protocol: str = "http") -> Dict[str, int]:
        """
        Migrate legacy proxy.txt files to database
        
        Args:
            file_paths: List of proxy file paths to migrate
            default_protocol: Default protocol for proxies without explicit protocol
            
        Returns:
            Migration statistics
        """
        self.logger.info(f"Starting migration of {len(file_paths)} files")
        
        stats = self.migrator.migrate_multiple_files(file_paths, default_protocol)
        
        self.logger.info(f"Migration completed: {stats}")
        return stats
    
    def add_proxy(self, proxy_string: str) -> Optional[int]:
        """
        Add a single proxy to the database
        
        Args:
            proxy_string: Proxy string in various formats
            
        Returns:
            Proxy ID if successful, None otherwise
        """
        # Validate and parse proxy string
        is_valid, parsed = self.validator.validate_proxy_string(proxy_string)
        
        if not is_valid or not parsed:
            errors = self.validator.get_validation_errors(proxy_string)
            self.logger.error(f"Invalid proxy string '{proxy_string}': {', '.join(errors)}")
            return None
        
        # Create proxy model
        proxy = ProxyModel(
            host=parsed['host'],
            port=int(parsed['port']),
            protocol=parsed['protocol'],
            username=parsed['username'],
            password=parsed['password']
        )
        
        try:
            proxy_id = self.db_manager.add_proxy(proxy)
            self.logger.info(f"Added proxy: {proxy.proxy_string}")
            return proxy_id
        except Exception as e:
            self.logger.error(f"Failed to add proxy: {e}")
            return None
    
    def check_proxies(self, protocol: Optional[str] = None,
                     limit: Optional[int] = None,
                     working_only: bool = False,
                     socketio=None) -> Dict[str, Any]:
        """
        Check proxies in the database

        Args:
            protocol: Filter by protocol
            limit: Maximum number of proxies to check
            working_only: Only check currently working proxies
            socketio: SocketIO instance for real-time updates

        Returns:
            Check results summary
        """
        # Get proxies to check
        proxies = self.db_manager.get_proxies(
            protocol=protocol,
            working_only=working_only,
            limit=limit
        )

        if not proxies:
            self.logger.info("No proxies found to check")
            return {'total': 0, 'checked': 0, 'working': 0, 'failed': 0}

        self.logger.info(f"Checking {len(proxies)} proxies...")

        # Emit start event
        if socketio:
            socketio.emit('activity_update', {
                'type': 'check_start',
                'message': f'Starting check of {len(proxies)} proxies...'
            })

        results = {
            'total': len(proxies),
            'checked': 0,
            'working': 0,
            'failed': 0,
            'results': []
        }

        for proxy in proxies:
            try:
                # Convert protocol string to enum
                protocol_enum = ProxyProtocol(proxy.protocol)

                # Check proxy
                check_result = self.proxy_checker.check_proxy(
                    host=proxy.host,
                    port=proxy.port,
                    protocol=protocol_enum,
                    username=proxy.username,
                    password=proxy.password
                )

                # Update database with results
                self.db_manager.update_proxy_stats(
                    proxy_id=proxy.id,
                    success=check_result.success,
                    response_time=check_result.response_time
                )

                # Update proxy working status
                self.db_manager.update_proxy_status(proxy.id, check_result.success)

                results['checked'] += 1
                if check_result.success:
                    results['working'] += 1
                    self.logger.info(f"✓ {proxy.host}:{proxy.port} - {check_result.response_time:.2f}s")
                    # Emit success event
                    if socketio:
                        socketio.emit('activity_update', {
                            'type': 'proxy_success',
                            'message': f'✓ {proxy.host}:{proxy.port} - {check_result.response_time:.2f}s'
                        })
                else:
                    results['failed'] += 1
                    self.logger.warning(f"✗ {proxy.host}:{proxy.port} - {check_result.error_message}")
                    # Emit failure event
                    if socketio:
                        socketio.emit('activity_update', {
                            'type': 'proxy_failure',
                            'message': f'✗ {proxy.host}:{proxy.port} - {check_result.error_message or "Connection failed"}'
                        })

                results['results'].append({
                    'proxy': f"{proxy.host}:{proxy.port}",
                    'protocol': proxy.protocol,
                    'success': check_result.success,
                    'response_time': check_result.response_time,
                    'error': check_result.error_message
                })

            except Exception as e:
                self.logger.error(f"Error checking proxy {proxy.host}:{proxy.port}: {e}")
                results['failed'] += 1
                # Emit error event
                if socketio:
                    socketio.emit('activity_update', {
                        'type': 'proxy_error',
                        'message': f'✗ {proxy.host}:{proxy.port} - Unexpected error: {str(e)}'
                    })
        
        self.logger.info(f"Check completed: {results['working']}/{results['checked']} working")

        # Emit completion event
        if socketio:
            socketio.emit('activity_update', {
                'type': 'check_complete',
                'message': f'Check completed: {results["working"]}/{results["checked"]} proxies working ({(results["working"]/results["checked"]*100):.1f}% success rate)' if results['checked'] > 0 else 'Check completed: No proxies checked'
            })

        return results
    
    def list_proxies(self, protocol: Optional[str] = None, 
                    working_only: bool = True, 
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List proxies in the database
        
        Args:
            protocol: Filter by protocol
            working_only: Only show working proxies
            limit: Maximum number of proxies to return
            
        Returns:
            List of proxy information
        """
        proxies = self.db_manager.get_proxies(
            protocol=protocol,
            working_only=working_only,
            limit=limit
        )
        
        proxy_list = []
        for proxy in proxies:
            stats = self.db_manager.get_proxy_stats(proxy.id)
            
            proxy_info = {
                'id': proxy.id,
                'host': proxy.host,
                'port': proxy.port,
                'protocol': proxy.protocol,
                'country': proxy.country,
                'city': proxy.city,
                'is_working': proxy.is_working,
                'created_at': proxy.created_at.isoformat() if proxy.created_at else None,
                'proxy_string': proxy.proxy_string
            }
            
            if stats:
                proxy_info.update({
                    'success_rate': stats.success_rate,
                    'total_checks': stats.total_checks,
                    'average_response_time': stats.average_response_time,
                    'last_check': stats.last_check.isoformat() if stats.last_check else None
                })
            
            proxy_list.append(proxy_info)
        
        return proxy_list
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive database and system statistics"""
        stats = self.db_manager.get_database_stats()

        # Add user agent rotation statistics if available
        ua_stats = self.proxy_checker.get_user_agent_stats()
        if ua_stats:
            stats['user_agent_rotation'] = ua_stats

        # Add memory statistics
        memory_stats = self.memory_manager.get_memory_stats()
        stats['memory'] = memory_stats

        return stats
    
    def cleanup_failed_proxies(self, max_failures: int = 5) -> int:
        """Remove proxies that have failed too many times"""
        deleted_count = self.db_manager.cleanup_failed_proxies(max_failures)
        self.logger.info(f"Cleaned up {deleted_count} failed proxies")
        return deleted_count
    
    def export_proxies(self, output_path: str, format_type: str = "txt",
                      protocol: Optional[str] = None, working_only: bool = True,
                      include_auth: bool = False, include_metadata: bool = True,
                      **format_options) -> int:
        """
        Export proxies to various formats (txt, json, csv, xml)

        Args:
            output_path: Output file path
            format_type: Export format (txt, json, csv, xml)
            protocol: Filter by protocol
            working_only: Only export working proxies
            include_auth: Include authentication in output
            include_metadata: Include metadata in export
            **format_options: Format-specific options

        Returns:
            Number of proxies exported
        """
        # For backward compatibility, handle text format
        if format_type.lower() in ['txt', 'text']:
            exported_count = self.migrator.export_to_text_file(
                output_path=output_path,
                protocol=protocol,
                working_only=working_only,
                include_auth=include_auth
            )
            self.logger.info(f"Exported {exported_count} proxies to text file: {output_path}")
            return exported_count

        # Get proxies for export
        proxies = self.list_proxies(protocol=protocol, working_only=working_only)

        if not proxies:
            self.logger.warning("No proxies found matching criteria")
            return 0

        # Prepare additional metadata
        additional_metadata = {
            'filter_protocol': protocol,
            'working_only': working_only,
            'include_auth': include_auth,
            'export_criteria': {
                'total_in_database': self.db_manager.get_proxy_count(),
                'filtered_count': len(proxies)
            }
        }

        # Export using the new system
        exported_count = self.export_manager.export(
            proxies=proxies,
            output_path=output_path,
            format_name=format_type,
            additional_metadata=additional_metadata,
            include_metadata=include_metadata,
            **format_options
        )

        self.logger.info(f"Exported {exported_count} proxies to {format_type.upper()}: {output_path}")
        return exported_count
    
    def create_default_config(self, config_path: str):
        """Create a default configuration file"""
        self.config_manager.create_default_config_file(config_path)
        self.logger.info(f"Default configuration created at {config_path}")
    
    def download_proxies(self, repository: Optional[str] = None,
                        protocol: Optional[str] = None) -> Dict[str, Any]:
        """
        Download proxies from GitHub sources

        Args:
            repository: Specific repository to download from
            protocol: Specific protocol to download

        Returns:
            Download results summary
        """
        self.logger.info("Starting proxy download from GitHub sources...")

        try:
            if repository:
                results = self.scrapers.scrape_by_repository(repository)
            elif protocol:
                results = self.scrapers.scrape_by_protocol(protocol)
            else:
                results = self.scrapers.scrape_all_sources()

            # Compile summary
            summary = {
                'total_sources': len(results),
                'successful_sources': sum(1 for r in results if r.success),
                'failed_sources': sum(1 for r in results if not r.success),
                'total_proxies_found': sum(r.proxies_found for r in results),
                'total_proxies_imported': sum(r.proxies_imported for r in results),
                'total_duplicates': sum(r.duplicates_skipped for r in results),
                'total_invalid': sum(r.invalid_proxies for r in results),
                'results': results
            }

            self.logger.info(f"Download completed: {summary['total_proxies_imported']} new proxies imported")
            return summary

        except Exception as e:
            self.logger.error(f"Error during proxy download: {e}")
            return {
                'total_sources': 0,
                'successful_sources': 0,
                'failed_sources': 0,
                'total_proxies_found': 0,
                'total_proxies_imported': 0,
                'total_duplicates': 0,
                'total_invalid': 0,
                'error': str(e),
                'results': []
            }

    def get_available_sources(self) -> Dict[str, Any]:
        """Get information about available proxy sources"""
        return self.scrapers.get_available_sources()

    def test_source_availability(self) -> Dict[str, bool]:
        """Test availability of proxy sources"""
        return self.scrapers.test_source_availability()

    def get_scraping_statistics(self) -> Dict[str, Any]:
        """Get comprehensive scraping statistics"""
        return self.scrapers.get_scraping_statistics()

    # Proxy List Management Methods

    def create_proxy_list(self, name: str, description: str = "",
                         source: str = "manual", tags: List[str] = None) -> int:
        """Create a new proxy list"""
        return self.proxy_list_manager.create_list(name, description, source, tags)

    def delete_proxy_list(self, name: str) -> bool:
        """Delete a proxy list"""
        return self.proxy_list_manager.delete_list(name)

    def list_proxy_lists(self) -> List[Dict[str, Any]]:
        """Get all proxy lists with metadata"""
        lists = self.proxy_list_manager.list_all_lists()
        return [
            {
                'name': lst.name,
                'description': lst.description,
                'created_at': lst.created_at.isoformat() if lst.created_at else None,
                'updated_at': lst.updated_at.isoformat() if lst.updated_at else None,
                'total_proxies': lst.total_proxies,
                'source': lst.source,
                'tags': lst.tags
            }
            for lst in lists
        ]

    def add_proxy_to_list(self, list_name: str, proxy_string: str) -> bool:
        """Add a proxy to a specific list"""
        # Validate and parse proxy string
        is_valid, parsed = self.validator.validate_proxy_string(proxy_string)

        if not is_valid or not parsed:
            errors = self.validator.get_validation_errors(proxy_string)
            self.logger.error(f"Invalid proxy string '{proxy_string}': {', '.join(errors)}")
            return False

        # Create proxy model
        proxy = ProxyModel(
            host=parsed['host'],
            port=int(parsed['port']),
            protocol=parsed['protocol'],
            username=parsed['username'],
            password=parsed['password']
        )

        return self.proxy_list_manager.add_proxy_to_list(list_name, proxy)

    def get_list_proxies(self, list_name: str, working_only: bool = True,
                        limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get proxies from a specific list"""
        proxies = self.proxy_list_manager.get_list_proxies(list_name, working_only, limit)

        proxy_list = []
        for proxy in proxies:
            stats = self.db_manager.get_proxy_stats(proxy.id)

            proxy_info = {
                'id': proxy.id,
                'host': proxy.host,
                'port': proxy.port,
                'protocol': proxy.protocol,
                'country': proxy.country,
                'city': proxy.city,
                'is_working': proxy.is_working,
                'created_at': proxy.created_at.isoformat() if proxy.created_at else None,
                'proxy_string': proxy.proxy_string
            }

            if stats:
                proxy_info.update({
                    'success_rate': stats.success_rate,
                    'total_checks': stats.total_checks,
                    'average_response_time': stats.average_response_time,
                    'last_check': stats.last_check.isoformat() if stats.last_check else None
                })

            proxy_list.append(proxy_info)

        return proxy_list

    def get_list_statistics(self, list_name: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific proxy list"""
        stats = self.proxy_list_manager.get_list_stats(list_name)
        if not stats:
            return None

        return {
            'total_count': stats.total_count,
            'working_count': stats.working_count,
            'failed_count': stats.failed_count,
            'success_rate': stats.success_rate,
            'protocols': stats.protocols,
            'countries': stats.countries,
            'avg_response_time': stats.avg_response_time,
            'last_check': stats.last_check.isoformat() if stats.last_check else None
        }

    def close(self):
        """Clean up resources"""
        if hasattr(self, 'scrapers'):
            self.scrapers.close()
        if hasattr(self, 'memory_manager'):
            self.memory_manager.monitor.stop_monitoring()
        self.db_manager.close()
        self.logger.info("HiberProxy Enhanced shut down")


def create_argument_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser"""
    parser = argparse.ArgumentParser(
        description="HiberProxy Enhanced - Multi-Protocol Proxy Management System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s migrate proxy.txt                    # Migrate legacy proxy.txt file
  %(prog)s add "http://127.0.0.1:8080"         # Add a single proxy
  %(prog)s check --protocol http --limit 100   # Check 100 HTTP proxies
  %(prog)s list --working-only                 # List only working proxies
  %(prog)s export proxies.txt --protocol socks5 # Export SOCKS5 proxies
  %(prog)s stats                               # Show database statistics
  %(prog)s cleanup --max-failures 3           # Remove proxies with 3+ failures
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        help='Configuration file path',
        default=None
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Download command
    download_parser = subparsers.add_parser('download', help='Download proxies from GitHub sources')
    download_parser.add_argument('--repository', choices=['thespeedx', 'monosans', 'databay-labs', 'zloi-user'],
                                help='Download from specific repository')
    download_parser.add_argument('--protocol', choices=['http', 'https', 'socks4', 'socks5'],
                                help='Download specific protocol')
    download_parser.add_argument('--test-sources', action='store_true',
                                help='Test source availability before downloading')

    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Migrate legacy proxy files')
    migrate_parser.add_argument('files', nargs='+', help='Proxy files to migrate')
    migrate_parser.add_argument('--protocol', default='http', help='Default protocol')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a single proxy')
    add_parser.add_argument('proxy', help='Proxy string (various formats supported)')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check proxy connectivity')
    check_parser.add_argument('--protocol', help='Filter by protocol')
    check_parser.add_argument('--limit', type=int, help='Maximum number to check')
    check_parser.add_argument('--all', action='store_true', help='Check all proxies (including non-working)')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List proxies')
    list_parser.add_argument('--protocol', help='Filter by protocol')
    list_parser.add_argument('--limit', type=int, help='Maximum number to show')
    list_parser.add_argument('--all', action='store_true', help='Show all proxies (including non-working)')
    list_parser.add_argument('--format', choices=['table', 'json'], default='table', help='Output format')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export proxies to file')
    export_parser.add_argument('output', help='Output file path')
    export_parser.add_argument('--format', choices=['txt', 'json', 'csv', 'xml'],
                              default='txt', help='Export format (default: txt)')
    export_parser.add_argument('--protocol', help='Filter by protocol')
    export_parser.add_argument('--all', action='store_true', help='Export all proxies (including non-working)')
    export_parser.add_argument('--include-auth', action='store_true', help='Include authentication')
    export_parser.add_argument('--no-metadata', action='store_true', help='Exclude metadata from export')
    export_parser.add_argument('--indent', type=int, default=2, help='JSON indentation level (JSON format only)')
    export_parser.add_argument('--delimiter', default=',', help='CSV delimiter (CSV format only)')
    export_parser.add_argument('--columns', help='CSV columns (comma-separated, CSV format only)')
    
    # Stats command
    subparsers.add_parser('stats', help='Show database statistics')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Remove failed proxies')
    cleanup_parser.add_argument('--max-failures', type=int, default=5, help='Maximum consecutive failures')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Configuration management')
    config_parser.add_argument('--create-default', help='Create default config file')
    
    return parser


def print_table(data: List[Dict[str, Any]], headers: List[str]):
    """Print data in table format"""
    if not data:
        print("No data to display")
        return

    # Calculate column widths
    widths = {}
    for header in headers:
        widths[header] = len(header)
        for row in data:
            value = str(row.get(header, ''))
            widths[header] = max(widths[header], len(value))

    # Print header
    header_row = " | ".join(header.ljust(widths[header]) for header in headers)
    print(header_row)
    print("-" * len(header_row))

    # Print data rows
    for row in data:
        data_row = " | ".join(str(row.get(header, '')).ljust(widths[header]) for header in headers)
        print(data_row)


def main():
    """Main entry point"""
    parser = create_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        # Initialize application
        app = HiberProxyApp(args.config)

        # Set verbose logging if requested
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Execute command
        if args.command == 'download':
            # Test sources if requested
            if args.test_sources:
                print("Testing source availability...")
                availability = app.test_source_availability()
                for url, available in availability.items():
                    status = "✓ Available" if available else "✗ Unavailable"
                    print(f"  {url}: {status}")
                print()

            # Download proxies
            print("Downloading proxies from GitHub sources...")
            results = app.download_proxies(
                repository=args.repository,
                protocol=args.protocol
            )

            if 'error' in results:
                print(f"Download failed: {results['error']}")
                return 1

            print(f"Download completed:")
            print(f"  Sources processed: {results['successful_sources']}/{results['total_sources']}")
            print(f"  Proxies found: {results['total_proxies_found']}")
            print(f"  New proxies imported: {results['total_proxies_imported']}")
            print(f"  Duplicates skipped: {results['total_duplicates']}")
            print(f"  Invalid proxies: {results['total_invalid']}")

            # Show per-source results if verbose
            if args.verbose:
                print("\nDetailed results:")
                for result in results['results']:
                    status = "✓" if result.success else "✗"
                    print(f"  {status} {result.source_name}: {result.proxies_imported} imported")
                    if not result.success:
                        print(f"    Error: {result.error_message}")

        elif args.command == 'migrate':
            stats = app.migrate_legacy_files(args.files, args.protocol)
            print(f"Migration completed:")
            print(f"  Total processed: {stats['total_processed']}")
            print(f"  Successfully imported: {stats['successful_imports']}")
            print(f"  Failed imports: {stats['failed_imports']}")
            print(f"  Duplicates skipped: {stats['duplicates_skipped']}")
            print(f"  Invalid proxies: {stats['invalid_proxies']}")

        elif args.command == 'add':
            proxy_id = app.add_proxy(args.proxy)
            if proxy_id:
                print(f"Proxy added successfully (ID: {proxy_id})")
            else:
                print("Failed to add proxy")
                return 1

        elif args.command == 'check':
            results = app.check_proxies(
                protocol=args.protocol,
                limit=args.limit,
                working_only=not args.all
            )
            print(f"Check completed:")
            print(f"  Total checked: {results['checked']}")
            print(f"  Working: {results['working']}")
            print(f"  Failed: {results['failed']}")
            print(f"  Success rate: {results['working']/results['checked']*100:.1f}%" if results['checked'] > 0 else "  Success rate: 0%")

        elif args.command == 'list':
            proxies = app.list_proxies(
                protocol=args.protocol,
                working_only=not args.all,
                limit=args.limit
            )

            if args.format == 'json':
                import json
                print(json.dumps(proxies, indent=2))
            else:
                headers = ['id', 'host', 'port', 'protocol', 'is_working', 'success_rate', 'total_checks']
                print_table(proxies, headers)

        elif args.command == 'export':
            # Prepare format-specific options
            format_options = {}

            if args.format == 'json':
                format_options['indent'] = args.indent
            elif args.format == 'csv':
                format_options['delimiter'] = args.delimiter
                if args.columns:
                    format_options['columns'] = [col.strip() for col in args.columns.split(',')]

            count = app.export_proxies(
                output_path=args.output,
                format_type=args.format,
                protocol=args.protocol,
                working_only=not args.all,
                include_auth=args.include_auth,
                include_metadata=not args.no_metadata,
                **format_options
            )
            print(f"Exported {count} proxies to {args.output} ({args.format.upper()} format)")

        elif args.command == 'stats':
            stats = app.get_statistics()
            print("Database Statistics:")
            print(f"  Total proxies: {stats['total_proxies']}")
            print(f"  Working proxies: {stats['working_proxies']}")
            print(f"  Active sources: {stats['active_sources']}")
            print(f"  Average response time: {stats['average_response_time']:.2f}s")
            print(f"  Average success rate: {stats['average_success_rate']:.1f}%")

            print("\nBy Protocol:")
            for protocol, data in stats['protocols'].items():
                print(f"  {protocol.upper()}: {data['working']}/{data['total']} working")

            # Show user agent rotation statistics if available
            if 'user_agent_rotation' in stats:
                ua_stats = stats['user_agent_rotation']
                print("\nUser Agent Rotation:")
                print(f"  Total requests: {ua_stats['total_requests']}")
                print(f"  Unique agents used: {ua_stats['unique_agents_used']}")
                print(f"  Average success rate: {ua_stats['average_success_rate']:.1f}%")
                print(f"  Detection incidents: {ua_stats['detection_incidents']}")
                if ua_stats['current_agent']:
                    print(f"  Current agent: {ua_stats['current_agent']}")

                if ua_stats['category_distribution']:
                    print("  Category distribution:")
                    for category, count in ua_stats['category_distribution'].items():
                        print(f"    {category}: {count} requests")

        elif args.command == 'cleanup':
            count = app.cleanup_failed_proxies(args.max_failures)
            print(f"Removed {count} failed proxies")

        elif args.command == 'config':
            if args.create_default:
                app.create_default_config(args.create_default)
                print(f"Default configuration created at {args.create_default}")
            else:
                print("No config action specified")
                return 1

        # Clean up
        app.close()
        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
