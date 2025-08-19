"""
Memory Management for HiberProxy Enhanced

Provides efficient memory management for large proxy lists including:
- Streaming proxy processing
- Memory-efficient data structures
- Configurable memory limits
- Lazy loading and batch processing
- Memory monitoring and cleanup
"""

import gc
import sys
import psutil
import threading
import weakref
from typing import Iterator, List, Dict, Any, Optional, Callable, Generator
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)


@dataclass
class MemoryConfig:
    """Memory management configuration"""
    max_memory_mb: int = 512  # Maximum memory usage in MB
    batch_size: int = 1000    # Default batch size for processing
    cache_size: int = 10000   # Maximum items in cache
    gc_threshold: float = 0.8 # Trigger GC when memory usage exceeds this ratio
    enable_monitoring: bool = True
    cleanup_interval: int = 300  # Cleanup interval in seconds


class MemoryMonitor:
    """Monitor memory usage and trigger cleanup when needed"""
    
    def __init__(self, config: MemoryConfig):
        self.config = config
        self.process = psutil.Process()
        self._monitoring = False
        self._monitor_thread = None
        self._callbacks = []
        
    def start_monitoring(self):
        """Start memory monitoring in background thread"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Memory monitoring started")
    
    def stop_monitoring(self):
        """Stop memory monitoring"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        logger.info("Memory monitoring stopped")
    
    def add_cleanup_callback(self, callback: Callable[[], None]):
        """Add callback to be called when memory cleanup is needed"""
        self._callbacks.append(callback)
    
    def get_memory_usage(self) -> Dict[str, float]:
        """Get current memory usage statistics"""
        memory_info = self.process.memory_info()
        return {
            'rss_mb': memory_info.rss / 1024 / 1024,
            'vms_mb': memory_info.vms / 1024 / 1024,
            'percent': self.process.memory_percent(),
            'available_mb': psutil.virtual_memory().available / 1024 / 1024
        }
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self._monitoring:
            try:
                memory_usage = self.get_memory_usage()
                
                # Check if memory usage exceeds threshold
                if memory_usage['rss_mb'] > self.config.max_memory_mb * self.config.gc_threshold:
                    logger.warning(f"Memory usage high: {memory_usage['rss_mb']:.1f}MB")
                    self._trigger_cleanup()
                
                time.sleep(self.config.cleanup_interval)
                
            except Exception as e:
                logger.error(f"Error in memory monitoring: {e}")
                time.sleep(10)  # Wait before retrying
    
    def _trigger_cleanup(self):
        """Trigger memory cleanup"""
        logger.info("Triggering memory cleanup")
        
        # Call registered cleanup callbacks
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback: {e}")
        
        # Force garbage collection
        gc.collect()
        
        # Log memory usage after cleanup
        memory_usage = self.get_memory_usage()
        logger.info(f"Memory usage after cleanup: {memory_usage['rss_mb']:.1f}MB")


class StreamingProxyProcessor:
    """Process proxies in streaming fashion to minimize memory usage"""
    
    def __init__(self, config: MemoryConfig):
        self.config = config
        
    def process_file_stream(self, file_path: Path, 
                           processor: Callable[[str], Any]) -> Generator[Any, None, None]:
        """
        Process proxy file line by line without loading entire file into memory
        
        Args:
            file_path: Path to proxy file
            processor: Function to process each line
            
        Yields:
            Processed results
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    try:
                        result = processor(line)
                        if result is not None:
                            yield result
                    except Exception as e:
                        logger.warning(f"Error processing line {line_num}: {e}")
                    
                    # Trigger GC periodically
                    if line_num % self.config.batch_size == 0:
                        gc.collect()
                        
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            raise
    
    def process_batch_stream(self, items: List[Any], 
                           processor: Callable[[List[Any]], Any]) -> Generator[Any, None, None]:
        """
        Process items in batches to control memory usage
        
        Args:
            items: List of items to process
            processor: Function to process each batch
            
        Yields:
            Processed batch results
        """
        batch_size = self.config.batch_size
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            try:
                result = processor(batch)
                if result is not None:
                    yield result
            except Exception as e:
                logger.error(f"Error processing batch {i//batch_size + 1}: {e}")
            
            # Cleanup after each batch
            del batch
            if i % (batch_size * 10) == 0:  # Every 10 batches
                gc.collect()


class MemoryEfficientCache:
    """Memory-efficient cache with automatic cleanup"""
    
    def __init__(self, config: MemoryConfig):
        self.config = config
        self._cache = {}
        self._access_times = deque()
        self._lock = threading.RLock()
        
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache"""
        with self._lock:
            if key in self._cache:
                # Update access time
                self._access_times.append((key, time.time()))
                return self._cache[key]
            return None
    
    def put(self, key: str, value: Any):
        """Put item in cache with automatic cleanup"""
        with self._lock:
            # Check if cache is full
            if len(self._cache) >= self.config.cache_size:
                self._cleanup_old_entries()
            
            self._cache[key] = value
            self._access_times.append((key, time.time()))
    
    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            gc.collect()
    
    def _cleanup_old_entries(self):
        """Remove least recently used entries"""
        # Remove oldest 20% of entries
        remove_count = max(1, len(self._cache) // 5)
        
        # Sort by access time and remove oldest
        sorted_items = sorted(self._access_times, key=lambda x: x[1])
        for key, _ in sorted_items[:remove_count]:
            self._cache.pop(key, None)
        
        # Update access times
        self._access_times = deque(sorted_items[remove_count:])
        
        logger.debug(f"Cleaned up {remove_count} cache entries")


class MemoryManager:
    """Main memory manager coordinating all memory optimization features"""
    
    def __init__(self, config: Optional[MemoryConfig] = None):
        self.config = config or MemoryConfig()
        self.monitor = MemoryMonitor(self.config)
        self.processor = StreamingProxyProcessor(self.config)
        self.cache = MemoryEfficientCache(self.config)
        
        # Register cleanup callbacks
        self.monitor.add_cleanup_callback(self.cache.clear)
        self.monitor.add_cleanup_callback(self._force_gc)
        
        if self.config.enable_monitoring:
            self.monitor.start_monitoring()
    
    def __del__(self):
        """Cleanup when manager is destroyed"""
        self.monitor.stop_monitoring()
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics"""
        stats = self.monitor.get_memory_usage()
        stats.update({
            'cache_size': len(self.cache._cache),
            'max_cache_size': self.config.cache_size,
            'batch_size': self.config.batch_size,
            'gc_threshold_mb': self.config.max_memory_mb * self.config.gc_threshold
        })
        return stats
    
    def _force_gc(self):
        """Force garbage collection"""
        collected = gc.collect()
        logger.debug(f"Garbage collection freed {collected} objects")


# Global memory manager instance
_memory_manager = None
_manager_lock = threading.Lock()


def get_memory_manager(config: Optional[MemoryConfig] = None) -> MemoryManager:
    """Get global memory manager instance"""
    global _memory_manager
    
    with _manager_lock:
        if _memory_manager is None:
            _memory_manager = MemoryManager(config)
        return _memory_manager


def configure_memory_management(config: MemoryConfig):
    """Configure global memory management settings"""
    global _memory_manager
    
    with _manager_lock:
        if _memory_manager is not None:
            _memory_manager.monitor.stop_monitoring()
        _memory_manager = MemoryManager(config)
