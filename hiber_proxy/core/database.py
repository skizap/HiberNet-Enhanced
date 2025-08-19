"""
Database management for HiberProxy Enhanced

Provides SQLite database integration with connection pooling, ORM-like models,
and comprehensive proxy data management with statistics tracking.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass, asdict
import logging
import json

logger = logging.getLogger(__name__)


@dataclass
class ProxyModel:
    """Data model for proxy objects"""
    id: Optional[int] = None
    host: str = ""
    port: int = 0
    protocol: str = "http"  # http, https, socks4, socks5
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    is_working: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    @property
    def proxy_string(self) -> str:
        """Get proxy as string representation"""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @property
    def unique_key(self) -> str:
        """Get unique identifier for this proxy"""
        return f"{self.host}:{self.port}:{self.protocol}"


@dataclass
class ProxyStats:
    """Statistics model for proxy performance"""
    id: Optional[int] = None
    proxy_id: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_response_time: float = 0.0
    last_used: Optional[datetime] = None
    last_check: Optional[datetime] = None
    consecutive_failures: int = 0
    average_response_time: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 100.0
    
    @property
    def total_checks(self) -> int:
        """Get total number of checks performed"""
        return self.success_count + self.failure_count


@dataclass
class ProxySource:
    """Model for proxy sources"""
    id: Optional[int] = None
    url: str = ""
    name: str = ""
    is_active: bool = True
    last_scraped: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    proxies_found: int = 0
    scrape_interval: int = 3600  # seconds


class DatabaseManager:
    """Database manager with connection pooling and transaction support"""

    def __init__(self, db_path: str = "hiber_proxy.db", pool_size: int = 10,
                 timeout: int = 30):
        """
        Initialize database manager

        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
            timeout: Database operation timeout in seconds
        """
        self.db_path = Path(db_path)
        self.pool_size = pool_size
        self.timeout = timeout
        self._connections = []
        self._lock = threading.Lock()
        self._local = threading.local()

        # Create database and tables
        self._initialize_database()

        logger.info(f"Database manager initialized: {self.db_path} (timeout: {timeout}s)")
    
    def _initialize_database(self):
        """Create database tables if they don't exist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create proxies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    protocol TEXT NOT NULL DEFAULT 'http',
                    username TEXT,
                    password TEXT,
                    country TEXT,
                    city TEXT,
                    is_working BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(host, port, protocol)
                )
            """)
            
            # Create proxy_stats table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proxy_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_id INTEGER NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    total_response_time REAL DEFAULT 0.0,
                    last_used TIMESTAMP,
                    last_check TIMESTAMP,
                    consecutive_failures INTEGER DEFAULT 0,
                    average_response_time REAL DEFAULT 0.0,
                    FOREIGN KEY (proxy_id) REFERENCES proxies (id) ON DELETE CASCADE
                )
            """)
            
            # Create proxy_sources table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proxy_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    last_scraped TIMESTAMP,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    proxies_found INTEGER DEFAULT 0,
                    scrape_interval INTEGER DEFAULT 3600
                )
            """)
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_host_port ON proxies(host, port)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_protocol ON proxies(protocol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_working ON proxies(is_working)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats_proxy_id ON proxy_stats(proxy_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_active ON proxy_sources(is_active)")
            
            conn.commit()
            logger.debug("Database tables initialized")
    
    @contextmanager
    def get_connection(self):
        """Get database connection from pool"""
        conn = None
        try:
            with self._lock:
                if self._connections:
                    conn = self._connections.pop()
                else:
                    conn = sqlite3.connect(
                        self.db_path,
                        timeout=float(self.timeout),
                        check_same_thread=False
                    )
                    conn.row_factory = sqlite3.Row
                    # Enable foreign keys
                    conn.execute("PRAGMA foreign_keys = ON")
            
            yield conn
            
        finally:
            if conn:
                with self._lock:
                    if len(self._connections) < self.pool_size:
                        self._connections.append(conn)
                    else:
                        conn.close()
    
    def add_proxy(self, proxy: ProxyModel) -> int:
        """
        Add a new proxy to the database
        
        Args:
            proxy: ProxyModel instance
            
        Returns:
            ID of the inserted proxy
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO proxies (host, port, protocol, username, password, 
                                       country, city, is_working, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    proxy.host, proxy.port, proxy.protocol, proxy.username,
                    proxy.password, proxy.country, proxy.city, proxy.is_working,
                    proxy.created_at, proxy.updated_at
                ))
                
                proxy_id = cursor.lastrowid
                
                # Create initial stats record
                cursor.execute("""
                    INSERT INTO proxy_stats (proxy_id)
                    VALUES (?)
                """, (proxy_id,))
                
                conn.commit()
                logger.debug(f"Added proxy: {proxy.host}:{proxy.port} ({proxy.protocol})")
                return proxy_id
                
            except sqlite3.IntegrityError:
                # Proxy already exists, get its ID
                cursor.execute("""
                    SELECT id FROM proxies 
                    WHERE host = ? AND port = ? AND protocol = ?
                """, (proxy.host, proxy.port, proxy.protocol))
                
                result = cursor.fetchone()
                if result:
                    logger.debug(f"Proxy already exists: {proxy.host}:{proxy.port}")
                    return result[0]
                raise
    
    def get_proxy(self, proxy_id: int) -> Optional[ProxyModel]:
        """Get proxy by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_proxy_model(row)
            return None
    
    def get_proxies(self, protocol: Optional[str] = None, 
                   working_only: bool = True, limit: Optional[int] = None) -> List[ProxyModel]:
        """
        Get list of proxies with optional filtering
        
        Args:
            protocol: Filter by protocol (http, https, socks4, socks5)
            working_only: Only return working proxies
            limit: Maximum number of proxies to return
            
        Returns:
            List of ProxyModel instances
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM proxies WHERE 1=1"
            params = []
            
            if protocol:
                query += " AND protocol = ?"
                params.append(protocol)
            
            if working_only:
                query += " AND is_working = 1"
            
            query += " ORDER BY updated_at DESC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_proxy_model(row) for row in rows]

    def update_proxy_status(self, proxy_id: int, is_working: bool):
        """Update proxy working status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE proxies
                SET is_working = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (is_working, proxy_id))
            conn.commit()
            logger.debug(f"Updated proxy {proxy_id} status: {is_working}")

    def delete_proxy(self, proxy_id: int):
        """Delete proxy and its statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            conn.commit()
            logger.debug(f"Deleted proxy {proxy_id}")

    def update_proxy_stats(self, proxy_id: int, success: bool,
                          response_time: Optional[float] = None):
        """
        Update proxy statistics after a check

        Args:
            proxy_id: ID of the proxy
            success: Whether the check was successful
            response_time: Response time in seconds
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Get current stats
            cursor.execute("SELECT * FROM proxy_stats WHERE proxy_id = ?", (proxy_id,))
            row = cursor.fetchone()

            if not row:
                # Create stats record if it doesn't exist
                cursor.execute("""
                    INSERT INTO proxy_stats (proxy_id) VALUES (?)
                """, (proxy_id,))
                cursor.execute("SELECT * FROM proxy_stats WHERE proxy_id = ?", (proxy_id,))
                row = cursor.fetchone()

            # Update statistics
            if success:
                new_success = row['success_count'] + 1
                new_failures = row['failure_count']
                new_consecutive_failures = 0
            else:
                new_success = row['success_count']
                new_failures = row['failure_count'] + 1
                new_consecutive_failures = row['consecutive_failures'] + 1

            # Update response time statistics
            if response_time is not None and success:
                new_total_time = row['total_response_time'] + response_time
                new_avg_time = new_total_time / new_success if new_success > 0 else 0
            else:
                new_total_time = row['total_response_time']
                new_avg_time = row['average_response_time']

            cursor.execute("""
                UPDATE proxy_stats
                SET success_count = ?, failure_count = ?,
                    total_response_time = ?, average_response_time = ?,
                    consecutive_failures = ?, last_check = CURRENT_TIMESTAMP,
                    last_used = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_used END
                WHERE proxy_id = ?
            """, (
                new_success, new_failures, new_total_time, new_avg_time,
                new_consecutive_failures, success, proxy_id
            ))

            conn.commit()
            logger.debug(f"Updated stats for proxy {proxy_id}: success={success}")

    def get_proxy_stats(self, proxy_id: int) -> Optional[ProxyStats]:
        """Get statistics for a specific proxy"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM proxy_stats WHERE proxy_id = ?", (proxy_id,))
            row = cursor.fetchone()

            if row:
                return ProxyStats(
                    id=row['id'],
                    proxy_id=row['proxy_id'],
                    success_count=row['success_count'],
                    failure_count=row['failure_count'],
                    total_response_time=row['total_response_time'],
                    last_used=datetime.fromisoformat(row['last_used']) if row['last_used'] else None,
                    last_check=datetime.fromisoformat(row['last_check']) if row['last_check'] else None,
                    consecutive_failures=row['consecutive_failures'],
                    average_response_time=row['average_response_time']
                )
            return None

    def get_working_proxies_count(self, protocol: Optional[str] = None) -> int:
        """Get count of working proxies"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT COUNT(*) FROM proxies WHERE is_working = 1"
            params = []

            if protocol:
                query += " AND protocol = ?"
                params.append(protocol)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def get_total_proxies_count(self, protocol: Optional[str] = None) -> int:
        """Get total count of proxies"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT COUNT(*) FROM proxies"
            params = []

            if protocol:
                query += " WHERE protocol = ?"
                params.append(protocol)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def cleanup_failed_proxies(self, max_failures: int = 5):
        """Remove proxies that have failed too many times consecutively"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM proxies
                WHERE id IN (
                    SELECT p.id FROM proxies p
                    JOIN proxy_stats ps ON p.id = ps.proxy_id
                    WHERE ps.consecutive_failures >= ?
                )
            """, (max_failures,))

            deleted_count = cursor.rowcount
            conn.commit()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} failed proxies")

            return deleted_count

    def add_proxy_source(self, source: ProxySource) -> int:
        """Add a new proxy source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    INSERT INTO proxy_sources (url, name, is_active, scrape_interval)
                    VALUES (?, ?, ?, ?)
                """, (source.url, source.name, source.is_active, source.scrape_interval))

                source_id = cursor.lastrowid
                conn.commit()
                logger.debug(f"Added proxy source: {source.name}")
                return source_id

            except sqlite3.IntegrityError:
                # Source already exists
                cursor.execute("SELECT id FROM proxy_sources WHERE url = ?", (source.url,))
                result = cursor.fetchone()
                if result:
                    return result[0]
                raise

    def update_source_stats(self, source_id: int, success: bool, proxies_found: int = 0):
        """Update proxy source statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if success:
                cursor.execute("""
                    UPDATE proxy_sources
                    SET success_count = success_count + 1,
                        proxies_found = proxies_found + ?,
                        last_scraped = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (proxies_found, source_id))
            else:
                cursor.execute("""
                    UPDATE proxy_sources
                    SET failure_count = failure_count + 1,
                        last_scraped = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (source_id,))

            conn.commit()

    def get_active_sources(self) -> List[ProxySource]:
        """Get list of active proxy sources"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM proxy_sources
                WHERE is_active = 1
                ORDER BY success_count DESC
            """)
            rows = cursor.fetchall()

            sources = []
            for row in rows:
                source = ProxySource(
                    id=row['id'],
                    url=row['url'],
                    name=row['name'],
                    is_active=bool(row['is_active']),
                    last_scraped=datetime.fromisoformat(row['last_scraped']) if row['last_scraped'] else None,
                    success_count=row['success_count'],
                    failure_count=row['failure_count'],
                    proxies_found=row['proxies_found'],
                    scrape_interval=row['scrape_interval']
                )
                sources.append(source)

            return sources

    def _row_to_proxy_model(self, row) -> ProxyModel:
        """Convert database row to ProxyModel"""
        return ProxyModel(
            id=row['id'],
            host=row['host'],
            port=row['port'],
            protocol=row['protocol'],
            username=row['username'],
            password=row['password'],
            country=row['country'],
            city=row['city'],
            is_working=bool(row['is_working']),
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None
        )

    def backup_database(self, backup_path: Optional[str] = None):
        """Create a backup of the database"""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.db_path.stem}_backup_{timestamp}.db"

        backup_path = Path(backup_path)

        with self.get_connection() as conn:
            backup_conn = sqlite3.connect(backup_path)
            conn.backup(backup_conn)
            backup_conn.close()

        logger.info(f"Database backed up to {backup_path}")
        return backup_path

    def get_database_stats(self) -> Dict[str, Any]:
        """Get comprehensive database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # Proxy counts by protocol
            cursor.execute("""
                SELECT protocol, COUNT(*) as count,
                       SUM(CASE WHEN is_working THEN 1 ELSE 0 END) as working
                FROM proxies
                GROUP BY protocol
            """)

            protocol_stats = {}
            for row in cursor.fetchall():
                protocol_stats[row['protocol']] = {
                    'total': row['count'],
                    'working': row['working']
                }

            stats['protocols'] = protocol_stats

            # Overall statistics
            cursor.execute("SELECT COUNT(*) FROM proxies")
            stats['total_proxies'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM proxies WHERE is_working = 1")
            stats['working_proxies'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM proxy_sources WHERE is_active = 1")
            stats['active_sources'] = cursor.fetchone()[0]

            # Performance statistics
            cursor.execute("""
                SELECT AVG(average_response_time) as avg_response,
                       AVG(success_count * 100.0 / (success_count + failure_count)) as avg_success_rate
                FROM proxy_stats
                WHERE success_count + failure_count > 0
            """)

            perf_row = cursor.fetchone()
            if perf_row and perf_row['avg_response'] is not None:
                stats['average_response_time'] = perf_row['avg_response']
                stats['average_success_rate'] = perf_row['avg_success_rate']
            else:
                stats['average_response_time'] = 0.0
                stats['average_success_rate'] = 0.0

            return stats

    def close(self):
        """Close all database connections"""
        with self._lock:
            for conn in self._connections:
                conn.close()
            self._connections.clear()

        logger.info("Database connections closed")
