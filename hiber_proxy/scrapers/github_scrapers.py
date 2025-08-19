"""
GitHub-based proxy scrapers for HiberProxy Enhanced

Downloads and imports proxies from multiple GitHub-hosted proxy lists
with comprehensive error handling, rate limiting, and progress tracking.
"""

import requests
import time
import random
import re
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from urllib.parse import urlparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from ..core.database import DatabaseManager, ProxyModel, ProxySource
from ..core.validation import ProxyValidator
from ..core.protocols import ProtocolDetector, ProxyProtocol

logger = logging.getLogger(__name__)


@dataclass
class ScrapingConfig:
    """Configuration for proxy scraping operations"""
    request_timeout: int = 30
    retry_attempts: int = 3
    retry_delay_base: float = 2.0  # Base delay for exponential backoff
    max_retry_delay: float = 60.0
    request_delay_min: float = 2.0
    request_delay_max: float = 5.0
    concurrent_downloads: int = 3
    user_agent_rotation: bool = True
    respect_rate_limits: bool = True
    validate_before_import: bool = True


@dataclass
class ScrapingResult:
    """Result of a proxy scraping operation"""
    source_name: str
    source_url: str
    success: bool
    proxies_found: int = 0
    proxies_imported: int = 0
    duplicates_skipped: int = 0
    invalid_proxies: int = 0
    error_message: Optional[str] = None
    response_time: Optional[float] = None


class GitHubProxyScrapers:
    """GitHub-based proxy scraping system with rate limiting and error handling"""
    
    # Predefined GitHub proxy sources
    GITHUB_SOURCES = {
        'thespeedx': {
            'name': 'TheSpeedX SOCKS-List',
            'base_url': 'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/',
            'sources': {
                'socks5': 'socks5.txt',
                'socks4': 'socks4.txt',
                'http': 'http.txt'
            }
        },
        'monosans': {
            'name': 'monosans proxy-list',
            'base_url': 'https://raw.githubusercontent.com/monosans/proxy-list/refs/heads/main/proxies/',
            'sources': {
                'socks5': 'socks5.txt',
                'socks4': 'socks4.txt',
                'http': 'http.txt'
            }
        },
        'databay-labs': {
            'name': 'databay-labs free-proxy-list',
            'base_url': 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/',
            'sources': {
                'http': 'http.txt',
                'https': 'https.txt',
                'socks5': 'socks5.txt'
            }
        },
        'zloi-user': {
            'name': 'zloi-user hideip.me',
            'base_url': 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/',
            'sources': {
                'socks5': 'socks5.txt',
                'socks4': 'socks4.txt',
                'https': 'https.txt',
                'http': 'http.txt',
                'connect': 'connect.txt'  # Treat CONNECT as HTTP
            }
        }
    }
    
    # User agents for rotation
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0'
    ]
    
    def __init__(self, db_manager: DatabaseManager, validator: Optional[ProxyValidator] = None,
                 config: Optional[ScrapingConfig] = None):
        """
        Initialize GitHub proxy scrapers
        
        Args:
            db_manager: Database manager instance
            validator: Proxy validator instance
            config: Scraping configuration
        """
        self.db_manager = db_manager
        self.validator = validator
        self.config = config or ScrapingConfig()
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._last_request_time = 0
        
        # Initialize proxy sources in database
        self._initialize_sources()
        
        logger.info("GitHub proxy scrapers initialized")
    
    def _initialize_sources(self):
        """Initialize proxy sources in the database"""
        for repo_key, repo_info in self.GITHUB_SOURCES.items():
            for protocol, filename in repo_info['sources'].items():
                url = repo_info['base_url'] + filename
                source_name = f"{repo_info['name']} - {protocol.upper()}"
                
                # Map connect protocol to http
                db_protocol = 'http' if protocol == 'connect' else protocol
                
                source = ProxySource(
                    url=url,
                    name=source_name,
                    is_active=True,
                    scrape_interval=3600  # 1 hour default
                )
                
                try:
                    self.db_manager.add_proxy_source(source)
                    logger.debug(f"Added source: {source_name}")
                except Exception as e:
                    logger.debug(f"Source already exists: {source_name}")
    
    def _get_user_agent(self) -> str:
        """Get a random user agent for requests"""
        if self.config.user_agent_rotation:
            return random.choice(self.USER_AGENTS)
        return self.USER_AGENTS[0]
    
    def _rate_limit_delay(self):
        """Implement rate limiting between requests"""
        with self._lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            
            min_delay = self.config.request_delay_min
            max_delay = self.config.request_delay_max
            required_delay = random.uniform(min_delay, max_delay)
            
            if time_since_last < required_delay:
                sleep_time = required_delay - time_since_last
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)
            
            self._last_request_time = time.time()
    
    def _download_proxy_list(self, url: str, expected_protocol: str) -> Tuple[bool, List[str], str]:
        """
        Download proxy list from URL with retry logic
        
        Args:
            url: URL to download from
            expected_protocol: Expected protocol type
            
        Returns:
            Tuple of (success, proxy_lines, error_message)
        """
        for attempt in range(self.config.retry_attempts):
            try:
                # Rate limiting
                self._rate_limit_delay()
                
                # Prepare request
                headers = {
                    'User-Agent': self._get_user_agent(),
                    'Accept': 'text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Cache-Control': 'no-cache'
                }
                
                logger.debug(f"Downloading from {url} (attempt {attempt + 1})")
                
                start_time = time.time()
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.config.request_timeout,
                    allow_redirects=True
                )
                response_time = time.time() - start_time
                
                # Check for rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited by {url}, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                
                # Parse content
                content = response.text.strip()
                if not content:
                    return False, [], "Empty response"
                
                # Split into lines and filter
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                lines = [line for line in lines if not line.startswith('#')]  # Remove comments
                
                logger.debug(f"Downloaded {len(lines)} proxy lines from {url} in {response_time:.2f}s")
                return True, lines, ""
                
            except requests.exceptions.Timeout:
                error_msg = f"Timeout after {self.config.request_timeout}s"
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {error_msg}")
                
            except requests.exceptions.RequestException as e:
                error_msg = f"Request error: {str(e)}"
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {error_msg}")
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                logger.error(f"Attempt {attempt + 1} failed for {url}: {error_msg}")
            
            # Exponential backoff for retries
            if attempt < self.config.retry_attempts - 1:
                delay = min(
                    self.config.retry_delay_base * (2 ** attempt),
                    self.config.max_retry_delay
                )
                logger.debug(f"Retrying in {delay:.2f}s...")
                time.sleep(delay)
        
        return False, [], f"Failed after {self.config.retry_attempts} attempts"
    
    def _parse_proxy_line(self, line: str, expected_protocol: str) -> Optional[ProxyModel]:
        """
        Parse a single proxy line into ProxyModel
        
        Args:
            line: Proxy line to parse
            expected_protocol: Expected protocol type
            
        Returns:
            ProxyModel instance or None if invalid
        """
        line = line.strip()
        if not line:
            return None
        
        # Handle different formats
        # Format 1: IP:PORT
        if re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', line):
            host, port = line.split(':')
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=expected_protocol
            )
        
        # Format 2: protocol://IP:PORT
        protocol_match = re.match(r'^(https?|socks[45]?)://([^:]+):(\d+)$', line)
        if protocol_match:
            protocol, host, port = protocol_match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=protocol.lower()
            )
        
        # Format 3: protocol://username:password@IP:PORT
        auth_match = re.match(r'^(https?|socks[45]?)://([^:]+):([^@]+)@([^:]+):(\d+)$', line)
        if auth_match:
            protocol, username, password, host, port = auth_match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=protocol.lower(),
                username=username,
                password=password
            )
        
        # Format 4: IP:PORT:username:password
        auth_simple_match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', line)
        if auth_simple_match:
            host, port, username, password = auth_simple_match.groups()
            return ProxyModel(
                host=host,
                port=int(port),
                protocol=expected_protocol,
                username=username,
                password=password
            )
        
        logger.debug(f"Could not parse proxy line: {line}")
        return None
    
    def _import_proxies(self, proxy_lines: List[str], expected_protocol: str, 
                       source_id: int) -> Tuple[int, int, int]:
        """
        Import proxy lines into database
        
        Args:
            proxy_lines: List of proxy lines to import
            expected_protocol: Expected protocol type
            source_id: Source ID for tracking
            
        Returns:
            Tuple of (imported_count, duplicate_count, invalid_count)
        """
        imported_count = 0
        duplicate_count = 0
        invalid_count = 0
        
        for line in proxy_lines:
            try:
                proxy = self._parse_proxy_line(line, expected_protocol)
                if not proxy:
                    invalid_count += 1
                    continue
                
                # Validate if validator is available
                if self.config.validate_before_import and self.validator:
                    if not self.validator.validate_proxy_format(
                        proxy.host, proxy.port, proxy.protocol
                    ):
                        invalid_count += 1
                        logger.debug(f"Invalid proxy format: {line}")
                        continue
                
                # Try to add to database
                try:
                    proxy_id = self.db_manager.add_proxy(proxy)
                    imported_count += 1
                    logger.debug(f"Imported proxy: {proxy.host}:{proxy.port}")
                    
                except Exception as e:
                    if "UNIQUE constraint failed" in str(e):
                        duplicate_count += 1
                        logger.debug(f"Duplicate proxy: {proxy.host}:{proxy.port}")
                    else:
                        invalid_count += 1
                        logger.warning(f"Failed to import proxy {line}: {e}")
                        
            except Exception as e:
                invalid_count += 1
                logger.warning(f"Error processing proxy line '{line}': {e}")
        
        return imported_count, duplicate_count, invalid_count
    
    def scrape_source(self, source_url: str, source_name: str, 
                     expected_protocol: str) -> ScrapingResult:
        """
        Scrape proxies from a single source
        
        Args:
            source_url: URL to scrape from
            source_name: Name of the source
            expected_protocol: Expected protocol type
            
        Returns:
            ScrapingResult with operation details
        """
        logger.info(f"Scraping {source_name} ({expected_protocol.upper()}) from {source_url}")
        
        start_time = time.time()
        
        # Download proxy list
        success, proxy_lines, error_msg = self._download_proxy_list(source_url, expected_protocol)
        
        if not success:
            # Update source stats
            sources = self.db_manager.get_active_sources()
            for source in sources:
                if source.url == source_url:
                    self.db_manager.update_source_stats(source.id, False, 0)
                    break
            
            return ScrapingResult(
                source_name=source_name,
                source_url=source_url,
                success=False,
                error_message=error_msg,
                response_time=time.time() - start_time
            )
        
        # Import proxies
        imported, duplicates, invalid = self._import_proxies(
            proxy_lines, expected_protocol, 0  # We'll update this with proper source_id
        )
        
        # Update source stats
        sources = self.db_manager.get_active_sources()
        for source in sources:
            if source.url == source_url:
                self.db_manager.update_source_stats(source.id, True, imported)
                break
        
        response_time = time.time() - start_time
        
        result = ScrapingResult(
            source_name=source_name,
            source_url=source_url,
            success=True,
            proxies_found=len(proxy_lines),
            proxies_imported=imported,
            duplicates_skipped=duplicates,
            invalid_proxies=invalid,
            response_time=response_time
        )
        
        logger.info(f"Completed {source_name}: {imported} imported, {duplicates} duplicates, "
                   f"{invalid} invalid in {response_time:.2f}s")
        
        return result

    def scrape_all_sources(self, repo_filter: Optional[str] = None,
                          protocol_filter: Optional[str] = None) -> List[ScrapingResult]:
        """
        Scrape proxies from all configured sources

        Args:
            repo_filter: Filter by repository name (e.g., 'thespeedx')
            protocol_filter: Filter by protocol (e.g., 'socks5')

        Returns:
            List of ScrapingResult objects
        """
        sources_to_scrape = []

        for repo_key, repo_info in self.GITHUB_SOURCES.items():
            if repo_filter and repo_key != repo_filter:
                continue

            for protocol, filename in repo_info['sources'].items():
                if protocol_filter and protocol != protocol_filter:
                    continue

                url = repo_info['base_url'] + filename
                source_name = f"{repo_info['name']} - {protocol.upper()}"

                # Map connect protocol to http for database storage
                db_protocol = 'http' if protocol == 'connect' else protocol

                sources_to_scrape.append((url, source_name, db_protocol))

        logger.info(f"Starting scraping of {len(sources_to_scrape)} sources")

        results = []

        if self.config.concurrent_downloads > 1:
            # Concurrent scraping
            with ThreadPoolExecutor(max_workers=self.config.concurrent_downloads) as executor:
                future_to_source = {
                    executor.submit(self.scrape_source, url, name, protocol): (url, name, protocol)
                    for url, name, protocol in sources_to_scrape
                }

                for future in as_completed(future_to_source):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        url, name, protocol = future_to_source[future]
                        logger.error(f"Error scraping {name}: {e}")
                        results.append(ScrapingResult(
                            source_name=name,
                            source_url=url,
                            success=False,
                            error_message=str(e)
                        ))
        else:
            # Sequential scraping
            for url, name, protocol in sources_to_scrape:
                result = self.scrape_source(url, name, protocol)
                results.append(result)

        # Summary logging
        successful = sum(1 for r in results if r.success)
        total_imported = sum(r.proxies_imported for r in results)
        total_duplicates = sum(r.duplicates_skipped for r in results)
        total_invalid = sum(r.invalid_proxies for r in results)

        logger.info(f"Scraping completed: {successful}/{len(results)} sources successful, "
                   f"{total_imported} imported, {total_duplicates} duplicates, {total_invalid} invalid")

        return results

    def scrape_by_protocol(self, protocol: str) -> List[ScrapingResult]:
        """
        Scrape proxies for a specific protocol from all repositories

        Args:
            protocol: Protocol to scrape (http, https, socks4, socks5)

        Returns:
            List of ScrapingResult objects
        """
        return self.scrape_all_sources(protocol_filter=protocol)

    def scrape_by_repository(self, repository: str) -> List[ScrapingResult]:
        """
        Scrape all protocols from a specific repository

        Args:
            repository: Repository key (thespeedx, monosans, databay-labs, zloi-user)

        Returns:
            List of ScrapingResult objects
        """
        if repository not in self.GITHUB_SOURCES:
            raise ValueError(f"Unknown repository: {repository}. Available: {list(self.GITHUB_SOURCES.keys())}")

        return self.scrape_all_sources(repo_filter=repository)

    def get_available_sources(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get information about available scraping sources

        Returns:
            Dictionary with repository and protocol information
        """
        sources_info = {}

        for repo_key, repo_info in self.GITHUB_SOURCES.items():
            sources_info[repo_key] = {
                'name': repo_info['name'],
                'protocols': list(repo_info['sources'].keys()),
                'base_url': repo_info['base_url']
            }

        return sources_info

    def test_source_availability(self, max_test_sources: int = 3) -> Dict[str, bool]:
        """
        Test availability of proxy sources (quick connectivity check)

        Args:
            max_test_sources: Maximum number of sources to test

        Returns:
            Dictionary mapping source URLs to availability status
        """
        test_sources = []
        count = 0

        for repo_key, repo_info in self.GITHUB_SOURCES.items():
            if count >= max_test_sources:
                break

            # Test first protocol from each repo
            first_protocol = list(repo_info['sources'].keys())[0]
            filename = repo_info['sources'][first_protocol]
            url = repo_info['base_url'] + filename
            test_sources.append(url)
            count += 1

        availability = {}

        for url in test_sources:
            try:
                response = self.session.head(
                    url,
                    headers={'User-Agent': self._get_user_agent()},
                    timeout=10,
                    allow_redirects=True
                )
                availability[url] = response.status_code == 200
                logger.debug(f"Source {url}: {'Available' if availability[url] else 'Unavailable'}")

            except Exception as e:
                availability[url] = False
                logger.debug(f"Source {url}: Error - {e}")

        return availability

    def get_scraping_statistics(self) -> Dict[str, any]:
        """
        Get comprehensive scraping statistics from database

        Returns:
            Dictionary with scraping statistics
        """
        sources = self.db_manager.get_active_sources()

        stats = {
            'total_sources': len(sources),
            'sources_with_data': 0,
            'total_scrapes': 0,
            'successful_scrapes': 0,
            'total_proxies_found': 0,
            'sources_detail': []
        }

        for source in sources:
            if source.success_count > 0 or source.failure_count > 0:
                stats['sources_with_data'] += 1

            stats['total_scrapes'] += source.success_count + source.failure_count
            stats['successful_scrapes'] += source.success_count
            stats['total_proxies_found'] += source.proxies_found

            success_rate = (
                source.success_count / (source.success_count + source.failure_count) * 100
                if (source.success_count + source.failure_count) > 0 else 0
            )

            stats['sources_detail'].append({
                'name': source.name,
                'url': source.url,
                'success_count': source.success_count,
                'failure_count': source.failure_count,
                'success_rate': success_rate,
                'proxies_found': source.proxies_found,
                'last_scraped': source.last_scraped.isoformat() if source.last_scraped else None,
                'is_active': source.is_active
            })

        return stats

    def close(self):
        """Clean up resources"""
        if hasattr(self, 'session'):
            self.session.close()
        logger.debug("GitHub scrapers closed")
