#!/usr/bin/env python3
"""
HiberProxy Enhanced - Backward Compatible Wrapper

This script provides backward compatibility with the original HiberProxy.py
while leveraging the new enhanced multi-protocol proxy management system.
"""

import sys
import os
from pathlib import Path

# Add hiber_proxy to path
sys.path.insert(0, str(Path(__file__).parent))

from hiber_proxy.main import HiberProxyApp
from hiber_proxy.core.logging_config import setup_logging
from hiber_proxy.ui.interactive_menu import InteractiveMenuBuilder
import logging

# Set up basic logging for compatibility
setup_logging(log_level="INFO", enable_console=True, enable_file=False)
logger = logging.getLogger('hiber_proxy.compat')


def enhanced_interactive_main():
    """
    Enhanced interactive main function with improved menu system
    """
    try:
        # Initialize the enhanced app
        app = HiberProxyApp()

        # Create and run the enhanced menu system
        menu_builder = InteractiveMenuBuilder(app)
        main_menu = menu_builder.build_main_menu()

        # Run the interactive menu
        main_menu.run()

        # Cleanup
        app.close()

    except KeyboardInterrupt:
        print("\n\nExiting HiberProxy Enhanced...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error in interactive mode: {e}")
        print(f"\nFatal error: {e}")
        sys.exit(1)


def legacy_main():
    """
    Legacy main function that mimics the original HiberProxy.py behavior
    while using the enhanced backend system.
    """
    print("HiberProxy Enhanced - Multi-Protocol Proxy Management System")
    print("=" * 60)
    
    try:
        # Initialize the enhanced app
        app = HiberProxyApp()
        
        # Check if legacy proxy.txt exists and offer migration
        legacy_file = Path("proxy.txt")
        if legacy_file.exists():
            print(f"\nFound legacy proxy file: {legacy_file}")
            choice = input("Do you want to migrate it to the new database? [Y/n] > ").strip()
            
            if choice.lower() in ['', 'y', 'yes']:
                print("Migrating legacy proxy file...")
                stats = app.migrate_legacy_files([str(legacy_file)])
                print(f"Migration completed: {stats['successful_imports']} proxies imported")
                
                # Backup original file
                backup_path = legacy_file.with_suffix('.txt.backup')
                legacy_file.rename(backup_path)
                print(f"Original file backed up to: {backup_path}")
        
        while True:
            print("\nHiberProxy Enhanced Menu:")
            print("1. Download proxies from sources")
            print("2. Check existing proxies")
            print("3. List proxies")
            print("4. Add custom proxy")
            print("5. Export proxies")
            print("6. Show statistics")
            print("7. Cleanup failed proxies")
            print("8. Manage proxy lists")
            print("9. Exit")

            choice = input("\nSelect option [1-9] > ").strip()

            if choice == '1':
                download_proxies(app)
            elif choice == '2':
                check_proxies(app)
            elif choice == '3':
                list_proxies(app)
            elif choice == '4':
                add_custom_proxy(app)
            elif choice == '5':
                export_proxies(app)
            elif choice == '6':
                show_statistics(app)
            elif choice == '7':
                cleanup_proxies(app)
            elif choice == '8':
                manage_proxy_lists(app)
            elif choice == '9':
                print("Goodbye!")
                break
            else:
                print("Invalid choice. Please select 1-9.")
        
        app.close()
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        logger.error(f"Unexpected error: {e}", exc_info=True)


def download_proxies(app: HiberProxyApp):
    """Download proxies from GitHub sources"""
    print("\nProxy Download Options:")
    print("1. Download from all sources")
    print("2. Download specific protocol")
    print("3. Download from specific repository")
    print("4. Test source availability")
    print("5. Show available sources")

    choice = input("Select option [1-5] > ").strip()

    if choice == '4':
        print("\nTesting source availability...")
        availability = app.test_source_availability()
        for url, available in availability.items():
            status = "✓ Available" if available else "✗ Unavailable"
            print(f"  {url}: {status}")
        return

    elif choice == '5':
        print("\nAvailable Sources:")
        sources = app.get_available_sources()
        for repo_key, repo_info in sources.items():
            print(f"\n{repo_info['name']} ({repo_key}):")
            print(f"  Protocols: {', '.join(repo_info['protocols'])}")
            print(f"  Base URL: {repo_info['base_url']}")
        return

    repository = None
    protocol = None

    if choice == '2':
        protocol = input("Enter protocol (http/https/socks4/socks5) > ").strip().lower()
        if protocol not in ['http', 'https', 'socks4', 'socks5']:
            print("Invalid protocol.")
            return

    elif choice == '3':
        print("Available repositories:")
        print("1. thespeedx - TheSpeedX SOCKS-List")
        print("2. monosans - monosans proxy-list")
        print("3. databay-labs - databay-labs free-proxy-list")
        print("4. zloi-user - zloi-user hideip.me")

        repo_choice = input("Select repository [1-4] > ").strip()
        repo_map = {
            '1': 'thespeedx',
            '2': 'monosans',
            '3': 'databay-labs',
            '4': 'zloi-user'
        }

        if repo_choice not in repo_map:
            print("Invalid choice.")
            return

        repository = repo_map[repo_choice]

    elif choice != '1':
        print("Invalid choice.")
        return

    print(f"\nStarting download{f' (repository: {repository})' if repository else ''}"
          f"{f' (protocol: {protocol})' if protocol else ''}...")

    try:
        results = app.download_proxies(repository=repository, protocol=protocol)

        if 'error' in results:
            print(f"Download failed: {results['error']}")
            return

        print(f"\nDownload Results:")
        print(f"Sources processed: {results['successful_sources']}/{results['total_sources']}")
        print(f"Proxies found: {results['total_proxies_found']}")
        print(f"New proxies imported: {results['total_proxies_imported']}")
        print(f"Duplicates skipped: {results['total_duplicates']}")
        print(f"Invalid proxies: {results['total_invalid']}")

        # Show detailed results
        print(f"\nDetailed Results:")
        for result in results['results']:
            status = "✓" if result.success else "✗"
            if result.success:
                print(f"  {status} {result.source_name}: {result.proxies_imported} imported, "
                      f"{result.duplicates_skipped} duplicates")
            else:
                print(f"  {status} {result.source_name}: Failed - {result.error_message}")

    except Exception as e:
        print(f"Error during download: {e}")
        logger.error(f"Download error: {e}", exc_info=True)


def check_proxies(app: HiberProxyApp):
    """Check existing proxies"""
    print("\nProxy Checking Options:")
    print("1. Check all proxies")
    print("2. Check HTTP proxies only")
    print("3. Check SOCKS proxies only")
    print("4. Check specific number of proxies")
    
    choice = input("Select option [1-4] > ").strip()
    
    protocol = None
    limit = None
    
    if choice == '2':
        protocol = 'http'
    elif choice == '3':
        # Ask for SOCKS type
        socks_choice = input("SOCKS4 or SOCKS5? [4/5] > ").strip()
        protocol = f'socks{socks_choice}' if socks_choice in ['4', '5'] else 'socks5'
    elif choice == '4':
        try:
            limit = int(input("How many proxies to check? > ").strip())
        except ValueError:
            print("Invalid number. Checking all proxies.")
    
    print(f"\nChecking proxies{f' (protocol: {protocol})' if protocol else ''}...")
    
    results = app.check_proxies(protocol=protocol, limit=limit, working_only=False)
    
    print(f"\nCheck Results:")
    print(f"Total checked: {results['checked']}")
    print(f"Working: {results['working']}")
    print(f"Failed: {results['failed']}")
    
    if results['checked'] > 0:
        success_rate = results['working'] / results['checked'] * 100
        print(f"Success rate: {success_rate:.1f}%")


def list_proxies(app: HiberProxyApp):
    """List proxies in the database"""
    print("\nListing Options:")
    print("1. Show working proxies only")
    print("2. Show all proxies")
    print("3. Show by protocol")
    
    choice = input("Select option [1-3] > ").strip()
    
    working_only = True
    protocol = None
    
    if choice == '2':
        working_only = False
    elif choice == '3':
        protocol = input("Enter protocol (http/https/socks4/socks5) > ").strip().lower()
        if protocol not in ['http', 'https', 'socks4', 'socks5']:
            print("Invalid protocol. Showing all protocols.")
            protocol = None
    
    try:
        limit = int(input("Maximum number to show (0 for all) > ").strip())
        if limit == 0:
            limit = None
    except ValueError:
        limit = 50  # Default limit
    
    proxies = app.list_proxies(protocol=protocol, working_only=working_only, limit=limit)
    
    if not proxies:
        print("No proxies found.")
        return
    
    print(f"\nFound {len(proxies)} proxies:")
    print("-" * 80)
    print(f"{'ID':<5} {'Host':<20} {'Port':<6} {'Protocol':<8} {'Status':<8} {'Success%':<8}")
    print("-" * 80)
    
    for proxy in proxies:
        status = "Working" if proxy['is_working'] else "Failed"
        success_rate = proxy.get('success_rate', 0)
        
        print(f"{proxy['id']:<5} {proxy['host']:<20} {proxy['port']:<6} "
              f"{proxy['protocol']:<8} {status:<8} {success_rate:<8.1f}")


def add_custom_proxy(app: HiberProxyApp):
    """Add a custom proxy"""
    print("\nAdd Custom Proxy")
    print("Supported formats:")
    print("  - host:port")
    print("  - protocol://host:port")
    print("  - protocol://username:password@host:port")
    
    proxy_string = input("\nEnter proxy > ").strip()
    
    if not proxy_string:
        print("No proxy entered.")
        return
    
    proxy_id = app.add_proxy(proxy_string)
    
    if proxy_id:
        print(f"Proxy added successfully! (ID: {proxy_id})")
        
        # Ask if user wants to test it
        test_choice = input("Test proxy now? [Y/n] > ").strip()
        if test_choice.lower() in ['', 'y', 'yes']:
            # Get the proxy we just added
            proxy = app.db_manager.get_proxy(proxy_id)
            if proxy:
                from hiber_proxy.core.protocols import ProxyProtocol
                protocol_enum = ProxyProtocol(proxy.protocol)
                
                print("Testing proxy...")
                result = app.proxy_checker.check_proxy(
                    host=proxy.host,
                    port=proxy.port,
                    protocol=protocol_enum,
                    username=proxy.username,
                    password=proxy.password
                )
                
                if result.success:
                    print(f"✓ Proxy is working! Response time: {result.response_time:.2f}s")
                else:
                    print(f"✗ Proxy failed: {result.error_message}")
                
                # Update database with test result
                app.db_manager.update_proxy_stats(proxy_id, result.success, result.response_time)
                app.db_manager.update_proxy_status(proxy_id, result.success)
    else:
        print("Failed to add proxy. Please check the format.")


def export_proxies(app: HiberProxyApp):
    """Export proxies to file"""
    output_file = input("Output file name [proxies.txt] > ").strip()
    if not output_file:
        output_file = "proxies.txt"
    
    print("\nExport Options:")
    print("1. Working proxies only")
    print("2. All proxies")
    print("3. Specific protocol")
    
    choice = input("Select option [1-3] > ").strip()
    
    working_only = True
    protocol = None
    
    if choice == '2':
        working_only = False
    elif choice == '3':
        protocol = input("Enter protocol (http/https/socks4/socks5) > ").strip().lower()
        if protocol not in ['http', 'https', 'socks4', 'socks5']:
            print("Invalid protocol. Exporting all protocols.")
            protocol = None
    
    include_auth = input("Include authentication info? [y/N] > ").strip().lower() in ['y', 'yes']
    
    count = app.export_proxies(
        output_path=output_file,
        protocol=protocol,
        working_only=working_only,
        include_auth=include_auth
    )
    
    print(f"Exported {count} proxies to {output_file}")


def show_statistics(app: HiberProxyApp):
    """Show database statistics"""
    stats = app.get_statistics()
    
    print("\nDatabase Statistics:")
    print("=" * 40)
    print(f"Total proxies: {stats['total_proxies']}")
    print(f"Working proxies: {stats['working_proxies']}")
    print(f"Active sources: {stats['active_sources']}")
    print(f"Average response time: {stats['average_response_time']:.2f}s")
    print(f"Average success rate: {stats['average_success_rate']:.1f}%")
    
    print("\nBy Protocol:")
    print("-" * 30)
    for protocol, data in stats['protocols'].items():
        working_pct = (data['working'] / data['total'] * 100) if data['total'] > 0 else 0
        print(f"{protocol.upper():<8}: {data['working']:>4}/{data['total']:<4} ({working_pct:.1f}%)")

    # Memory statistics
    memory_stats = stats.get('memory', {})
    if memory_stats:
        print(f"\nMemory Usage:")
        print("-" * 30)
        print(f"RSS Memory: {memory_stats.get('rss_mb', 0):.1f} MB")
        print(f"Cache Size: {memory_stats.get('cache_size', 0)}")
        print(f"Max Cache: {memory_stats.get('max_cache_size', 0)}")
        print(f"Batch Size: {memory_stats.get('batch_size', 0)}")
        print(f"GC Threshold: {memory_stats.get('gc_threshold_mb', 0):.1f} MB")


def cleanup_proxies(app: HiberProxyApp):
    """Cleanup failed proxies"""
    try:
        max_failures = int(input("Maximum consecutive failures [5] > ").strip() or "5")
    except ValueError:
        max_failures = 5

    print(f"Removing proxies with {max_failures}+ consecutive failures...")
    count = app.cleanup_failed_proxies(max_failures)
    print(f"Removed {count} failed proxies.")


def manage_proxy_lists(app: HiberProxyApp):
    """Manage multiple proxy lists"""
    while True:
        print("\nProxy List Management")
        print("=" * 40)
        print("1. List all proxy lists")
        print("2. Create new proxy list")
        print("3. View proxy list contents")
        print("4. Add proxy to list")
        print("5. List statistics")
        print("6. Delete proxy list")
        print("0. Back to main menu")

        choice = input("\nSelect option [0-6] > ").strip()

        if choice == '0':
            break
        elif choice == '1':
            list_proxy_lists(app)
        elif choice == '2':
            create_proxy_list(app)
        elif choice == '3':
            view_proxy_list(app)
        elif choice == '4':
            add_proxy_to_list(app)
        elif choice == '5':
            show_list_statistics(app)
        elif choice == '6':
            delete_proxy_list(app)
        else:
            print("Invalid choice.")


def list_proxy_lists(app: HiberProxyApp):
    """List all proxy lists"""
    lists = app.list_proxy_lists()

    if not lists:
        print("No proxy lists found.")
        return

    print(f"\nProxy Lists ({len(lists)} total):")
    print("-" * 60)
    for lst in lists:
        print(f"Name: {lst['name']}")
        print(f"  Description: {lst['description'] or 'No description'}")
        print(f"  Proxies: {lst['total_proxies']}")
        print(f"  Source: {lst['source']}")
        print(f"  Created: {lst['created_at'][:19] if lst['created_at'] else 'Unknown'}")
        if lst['tags']:
            print(f"  Tags: {', '.join(lst['tags'])}")
        print()


def create_proxy_list(app: HiberProxyApp):
    """Create a new proxy list"""
    name = input("List name > ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    description = input("Description (optional) > ").strip()
    source = input("Source [manual] > ").strip() or "manual"
    tags_input = input("Tags (comma-separated, optional) > ").strip()
    tags = [tag.strip() for tag in tags_input.split(',')] if tags_input else []

    try:
        list_id = app.create_proxy_list(name, description, source, tags)
        print(f"Created proxy list '{name}' with ID {list_id}")
    except Exception as e:
        print(f"Error creating list: {e}")


def view_proxy_list(app: HiberProxyApp):
    """View contents of a proxy list"""
    name = input("List name > ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    try:
        limit = int(input("Maximum to show (0 for all) > ").strip() or "50")
        if limit == 0:
            limit = None
    except ValueError:
        limit = 50

    working_only = input("Show working proxies only? [y/N] > ").strip().lower() == 'y'

    proxies = app.get_list_proxies(name, working_only, limit)

    if not proxies:
        print(f"No proxies found in list '{name}'.")
        return

    print(f"\nProxies in '{name}' ({len(proxies)} shown):")
    print("-" * 80)
    for proxy in proxies:
        status = "✓" if proxy['is_working'] else "✗"
        print(f"{status} {proxy['host']}:{proxy['port']} ({proxy['protocol'].upper()})")
        if proxy.get('country'):
            print(f"    Location: {proxy['country']}")
        if proxy.get('success_rate') is not None:
            print(f"    Success: {proxy['success_rate']:.1f}% "
                  f"({proxy['total_checks']} checks)")
        print()


def add_proxy_to_list(app: HiberProxyApp):
    """Add a proxy to a specific list"""
    name = input("List name > ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    proxy_string = input("Proxy (host:port or protocol://host:port) > ").strip()
    if not proxy_string:
        print("Proxy cannot be empty.")
        return

    try:
        success = app.add_proxy_to_list(name, proxy_string)
        if success:
            print(f"Added proxy to list '{name}'")
        else:
            print("Proxy already exists in list or invalid format")
    except Exception as e:
        print(f"Error adding proxy: {e}")


def show_list_statistics(app: HiberProxyApp):
    """Show statistics for a proxy list"""
    name = input("List name > ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    stats = app.get_list_statistics(name)
    if not stats:
        print(f"List '{name}' not found.")
        return

    print(f"\nStatistics for '{name}':")
    print("-" * 40)
    print(f"Total proxies: {stats['total_count']}")
    print(f"Working: {stats['working_count']}")
    print(f"Failed: {stats['failed_count']}")
    print(f"Success rate: {stats['success_rate']:.1f}%")

    if stats['protocols']:
        print(f"\nBy Protocol:")
        for protocol, count in stats['protocols'].items():
            print(f"  {protocol.upper()}: {count}")

    if stats['countries']:
        print(f"\nTop Countries:")
        for country, count in list(stats['countries'].items())[:5]:
            print(f"  {country}: {count}")


def delete_proxy_list(app: HiberProxyApp):
    """Delete a proxy list"""
    name = input("List name > ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    confirm = input(f"Delete list '{name}'? [y/N] > ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return

    try:
        success = app.delete_proxy_list(name)
        if success:
            print(f"Deleted list '{name}'")
        else:
            print(f"List '{name}' not found")
    except Exception as e:
        print(f"Error deleting list: {e}")


if __name__ == '__main__':
    # Check if running as legacy mode or new CLI mode
    if len(sys.argv) > 1:
        # Check for special flags
        if '--legacy' in sys.argv:
            # Remove the flag and run legacy mode
            sys.argv.remove('--legacy')
            if len(sys.argv) == 1:
                legacy_main()
            else:
                from hiber_proxy.main import main
                sys.exit(main())
        else:
            # New CLI mode - delegate to main CLI
            from hiber_proxy.main import main
            sys.exit(main())
    else:
        # Enhanced interactive mode by default
        enhanced_interactive_main()
