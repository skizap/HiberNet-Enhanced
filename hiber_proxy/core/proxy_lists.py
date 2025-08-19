"""
Multiple Proxy Lists Management

Provides support for managing and organizing multiple separate proxy lists:
- Named proxy lists with metadata
- Cross-list operations and deduplication
- List-specific configurations
- Import/export functionality
- List statistics and monitoring
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

from .database import DatabaseManager, ProxyModel
from .validation import ProxyValidator
from ..utils.config import ProxyListConfig

logger = logging.getLogger(__name__)


@dataclass
class ProxyListMetadata:
    """Metadata for a proxy list"""
    name: str
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    total_proxies: int = 0
    working_proxies: int = 0
    source: str = "manual"
    tags: List[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        if self.tags is None:
            self.tags = []


@dataclass
class ProxyListStats:
    """Statistics for a proxy list"""
    total_count: int = 0
    working_count: int = 0
    failed_count: int = 0
    protocols: Dict[str, int] = None
    countries: Dict[str, int] = None
    avg_response_time: float = 0.0
    last_check: Optional[datetime] = None
    
    def __post_init__(self):
        if self.protocols is None:
            self.protocols = {}
        if self.countries is None:
            self.countries = {}
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        total = self.working_count + self.failed_count
        return (self.working_count / total * 100) if total > 0 else 0.0


class ProxyListManager:
    """Manager for multiple proxy lists"""
    
    def __init__(self, db_manager: DatabaseManager, config: ProxyListConfig):
        self.db_manager = db_manager
        self.config = config
        self.validator = ProxyValidator()
        self._lock = threading.RLock()
        
        # Storage path for list metadata
        self.storage_path = Path(config.list_storage_path)
        self.storage_path.mkdir(exist_ok=True)
        
        # Initialize database tables for proxy lists
        self._initialize_list_tables()
        
        logger.info(f"Proxy list manager initialized with storage: {self.storage_path}")
    
    def _initialize_list_tables(self):
        """Initialize database tables for proxy list management"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create proxy_lists table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proxy_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'manual',
                    tags TEXT DEFAULT '[]',
                    is_active BOOLEAN DEFAULT 1
                )
            """)
            
            # Create proxy_list_members table (many-to-many relationship)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proxy_list_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    proxy_id INTEGER NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (list_id) REFERENCES proxy_lists (id) ON DELETE CASCADE,
                    FOREIGN KEY (proxy_id) REFERENCES proxies (id) ON DELETE CASCADE,
                    UNIQUE(list_id, proxy_id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_list_members_list_id ON proxy_list_members(list_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_list_members_proxy_id ON proxy_list_members(proxy_id)")
            
            conn.commit()
    
    def create_list(self, name: str, description: str = "", source: str = "manual", 
                   tags: List[str] = None) -> int:
        """
        Create a new proxy list
        
        Args:
            name: List name (must be unique)
            description: List description
            source: Source of the list
            tags: List tags
            
        Returns:
            List ID
        """
        with self._lock:
            if tags is None:
                tags = []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                try:
                    cursor.execute("""
                        INSERT INTO proxy_lists (name, description, source, tags)
                        VALUES (?, ?, ?, ?)
                    """, (name, description, source, json.dumps(tags)))
                    
                    list_id = cursor.lastrowid
                    conn.commit()
                    
                    logger.info(f"Created proxy list '{name}' with ID {list_id}")
                    return list_id
                    
                except sqlite3.IntegrityError:
                    raise ValueError(f"Proxy list '{name}' already exists")
    
    def delete_list(self, name: str) -> bool:
        """
        Delete a proxy list
        
        Args:
            name: List name
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("DELETE FROM proxy_lists WHERE name = ?", (name,))
                deleted = cursor.rowcount > 0
                conn.commit()
                
                if deleted:
                    logger.info(f"Deleted proxy list '{name}'")
                else:
                    logger.warning(f"Proxy list '{name}' not found")
                
                return deleted
    
    def list_all_lists(self) -> List[ProxyListMetadata]:
        """Get all proxy lists with metadata"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT pl.name, pl.description, pl.created_at, pl.updated_at, 
                       pl.source, pl.tags, COUNT(plm.proxy_id) as total_proxies
                FROM proxy_lists pl
                LEFT JOIN proxy_list_members plm ON pl.id = plm.list_id
                WHERE pl.is_active = 1
                GROUP BY pl.id, pl.name, pl.description, pl.created_at, pl.updated_at, pl.source, pl.tags
                ORDER BY pl.name
            """)
            
            lists = []
            for row in cursor.fetchall():
                metadata = ProxyListMetadata(
                    name=row[0],
                    description=row[1],
                    created_at=datetime.fromisoformat(row[2]) if row[2] else None,
                    updated_at=datetime.fromisoformat(row[3]) if row[3] else None,
                    source=row[4],
                    tags=json.loads(row[5]) if row[5] else [],
                    total_proxies=row[6]
                )
                lists.append(metadata)
            
            return lists
    
    def add_proxy_to_list(self, list_name: str, proxy: ProxyModel) -> bool:
        """
        Add a proxy to a specific list
        
        Args:
            list_name: Name of the list
            proxy: Proxy to add
            
        Returns:
            True if added, False if already exists
        """
        with self._lock:
            # First add proxy to main database
            proxy_id = self.db_manager.add_proxy(proxy)
            
            # Then add to list
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get list ID
                cursor.execute("SELECT id FROM proxy_lists WHERE name = ?", (list_name,))
                list_row = cursor.fetchone()
                if not list_row:
                    raise ValueError(f"Proxy list '{list_name}' not found")
                
                list_id = list_row[0]
                
                try:
                    cursor.execute("""
                        INSERT INTO proxy_list_members (list_id, proxy_id)
                        VALUES (?, ?)
                    """, (list_id, proxy_id))
                    
                    # Update list timestamp
                    cursor.execute("""
                        UPDATE proxy_lists SET updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (list_id,))
                    
                    conn.commit()
                    return True
                    
                except sqlite3.IntegrityError:
                    # Proxy already in list
                    return False
    
    def remove_proxy_from_list(self, list_name: str, proxy_id: int) -> bool:
        """
        Remove a proxy from a specific list
        
        Args:
            list_name: Name of the list
            proxy_id: ID of proxy to remove
            
        Returns:
            True if removed, False if not found
        """
        with self._lock:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM proxy_list_members 
                    WHERE list_id = (SELECT id FROM proxy_lists WHERE name = ?)
                    AND proxy_id = ?
                """, (list_name, proxy_id))
                
                removed = cursor.rowcount > 0
                
                if removed:
                    # Update list timestamp
                    cursor.execute("""
                        UPDATE proxy_lists SET updated_at = CURRENT_TIMESTAMP
                        WHERE name = ?
                    """, (list_name,))
                
                conn.commit()
                return removed
    
    def get_list_proxies(self, list_name: str, working_only: bool = True, 
                        limit: Optional[int] = None) -> List[ProxyModel]:
        """
        Get all proxies from a specific list
        
        Args:
            list_name: Name of the list
            working_only: Only return working proxies
            limit: Maximum number of proxies to return
            
        Returns:
            List of proxies
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT p.* FROM proxies p
                JOIN proxy_list_members plm ON p.id = plm.proxy_id
                JOIN proxy_lists pl ON plm.list_id = pl.id
                WHERE pl.name = ?
            """
            params = [list_name]
            
            if working_only:
                query += " AND p.is_working = 1"
            
            query += " ORDER BY plm.added_at DESC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(query, params)
            
            proxies = []
            for row in cursor.fetchall():
                proxy = self.db_manager._row_to_proxy_model(row)
                proxies.append(proxy)
            
            return proxies
    
    def get_list_stats(self, list_name: str) -> Optional[ProxyListStats]:
        """
        Get statistics for a specific list
        
        Args:
            list_name: Name of the list
            
        Returns:
            List statistics or None if list not found
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if list exists
            cursor.execute("SELECT id FROM proxy_lists WHERE name = ?", (list_name,))
            if not cursor.fetchone():
                return None
            
            # Get basic counts
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN p.is_working = 1 THEN 1 ELSE 0 END) as working,
                    SUM(CASE WHEN p.is_working = 0 THEN 1 ELSE 0 END) as failed
                FROM proxies p
                JOIN proxy_list_members plm ON p.id = plm.proxy_id
                JOIN proxy_lists pl ON plm.list_id = pl.id
                WHERE pl.name = ?
            """, (list_name,))
            
            counts = cursor.fetchone()
            
            # Get protocol distribution
            cursor.execute("""
                SELECT p.protocol, COUNT(*) as count
                FROM proxies p
                JOIN proxy_list_members plm ON p.id = plm.proxy_id
                JOIN proxy_lists pl ON plm.list_id = pl.id
                WHERE pl.name = ?
                GROUP BY p.protocol
            """, (list_name,))
            
            protocols = dict(cursor.fetchall())
            
            # Get country distribution
            cursor.execute("""
                SELECT p.country, COUNT(*) as count
                FROM proxies p
                JOIN proxy_list_members plm ON p.id = plm.proxy_id
                JOIN proxy_lists pl ON plm.list_id = pl.id
                WHERE pl.name = ? AND p.country IS NOT NULL
                GROUP BY p.country
                ORDER BY count DESC
                LIMIT 10
            """, (list_name,))
            
            countries = dict(cursor.fetchall())
            
            return ProxyListStats(
                total_count=counts[0] or 0,
                working_count=counts[1] or 0,
                failed_count=counts[2] or 0,
                protocols=protocols,
                countries=countries
            )
