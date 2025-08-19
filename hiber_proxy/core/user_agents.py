"""
Intelligent User Agent Rotation System for HiberProxy Enhanced

Provides smart user agent rotation with usage pattern tracking and detection avoidance.
"""

import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

from .exceptions import ConfigurationError
from .error_handler import handle_errors

logger = logging.getLogger(__name__)


class UserAgentCategory(Enum):
    """User agent categories for better rotation"""
    CHROME = "chrome"
    FIREFOX = "firefox"
    SAFARI = "safari"
    EDGE = "edge"
    MOBILE = "mobile"
    BOT = "bot"


@dataclass
class UserAgentInfo:
    """Information about a user agent"""
    agent_string: str
    category: UserAgentCategory
    popularity_score: float = 1.0  # Higher = more common
    last_used: Optional[datetime] = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate for this user agent"""
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0.0
    
    @property
    def is_recently_used(self) -> bool:
        """Check if user agent was used recently"""
        if not self.last_used:
            return False
        return datetime.now() - self.last_used < timedelta(minutes=30)


@dataclass
class RotationStats:
    """Statistics for user agent rotation"""
    total_requests: int = 0
    unique_agents_used: int = 0
    category_distribution: Dict[str, int] = field(default_factory=dict)
    average_success_rate: float = 0.0
    detection_incidents: int = 0
    last_rotation_time: Optional[datetime] = None


class UserAgentDatabase:
    """Database of user agents with categorization"""
    
    def __init__(self):
        self.user_agents: Dict[str, UserAgentInfo] = {}
        self._initialize_default_agents()
    
    def _initialize_default_agents(self):
        """Initialize with a comprehensive set of modern user agents"""
        
        # Chrome user agents (most popular)
        chrome_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        ]
        
        # Firefox user agents
        firefox_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        
        # Safari user agents
        safari_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]
        
        # Edge user agents
        edge_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ]
        
        # Mobile user agents
        mobile_agents = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        ]
        
        # Add Chrome agents (highest popularity)
        for agent in chrome_agents:
            self.add_user_agent(agent, UserAgentCategory.CHROME, popularity_score=3.0)
        
        # Add Firefox agents
        for agent in firefox_agents:
            self.add_user_agent(agent, UserAgentCategory.FIREFOX, popularity_score=2.0)
        
        # Add Safari agents
        for agent in safari_agents:
            self.add_user_agent(agent, UserAgentCategory.SAFARI, popularity_score=1.5)
        
        # Add Edge agents
        for agent in edge_agents:
            self.add_user_agent(agent, UserAgentCategory.EDGE, popularity_score=1.2)
        
        # Add Mobile agents
        for agent in mobile_agents:
            self.add_user_agent(agent, UserAgentCategory.MOBILE, popularity_score=2.5)
        
        logger.info(f"Initialized user agent database with {len(self.user_agents)} agents")
    
    def add_user_agent(self, agent_string: str, category: UserAgentCategory, 
                      popularity_score: float = 1.0):
        """Add a user agent to the database"""
        self.user_agents[agent_string] = UserAgentInfo(
            agent_string=agent_string,
            category=category,
            popularity_score=popularity_score
        )
    
    def get_agents_by_category(self, category: UserAgentCategory) -> List[UserAgentInfo]:
        """Get all user agents in a specific category"""
        return [agent for agent in self.user_agents.values() if agent.category == category]
    
    def get_all_agents(self) -> List[UserAgentInfo]:
        """Get all user agents"""
        return list(self.user_agents.values())
    
    def update_agent_stats(self, agent_string: str, success: bool):
        """Update statistics for a user agent"""
        if agent_string in self.user_agents:
            agent = self.user_agents[agent_string]
            agent.usage_count += 1
            agent.last_used = datetime.now()
            
            if success:
                agent.success_count += 1
            else:
                agent.failure_count += 1


class IntelligentUserAgentRotator:
    """Intelligent user agent rotation system with detection avoidance"""
    
    def __init__(self, min_rotation_interval: int = 300, 
                 max_same_agent_usage: int = 10,
                 detection_threshold: float = 20.0):
        """
        Initialize the user agent rotator
        
        Args:
            min_rotation_interval: Minimum seconds between rotations
            max_same_agent_usage: Maximum times to use same agent consecutively
            detection_threshold: Success rate threshold below which to avoid agent
        """
        self.database = UserAgentDatabase()
        self.min_rotation_interval = min_rotation_interval
        self.max_same_agent_usage = max_same_agent_usage
        self.detection_threshold = detection_threshold
        
        self.current_agent: Optional[str] = None
        self.current_agent_usage = 0
        self.last_rotation_time = datetime.now()
        self.stats = RotationStats()
        
        # Rotation strategy weights
        self.strategy_weights = {
            'popularity': 0.3,    # Prefer popular agents
            'success_rate': 0.4,  # Prefer successful agents
            'freshness': 0.2,     # Prefer less recently used agents
            'randomness': 0.1     # Add some randomness
        }
    
    @handle_errors(operation="user_agent_rotation")
    def get_user_agent(self, force_rotation: bool = False, 
                      preferred_category: Optional[UserAgentCategory] = None) -> str:
        """
        Get a user agent with intelligent rotation
        
        Args:
            force_rotation: Force selection of new agent
            preferred_category: Prefer agents from specific category
            
        Returns:
            User agent string
        """
        should_rotate = (
            force_rotation or
            self.current_agent is None or
            self._should_rotate_agent()
        )
        
        if should_rotate:
            self.current_agent = self._select_optimal_agent(preferred_category)
            self.current_agent_usage = 0
            self.last_rotation_time = datetime.now()
            self.stats.last_rotation_time = datetime.now()
            
            logger.debug(f"Rotated to new user agent: {self.current_agent[:50]}...")
        
        self.current_agent_usage += 1
        self.stats.total_requests += 1
        
        return self.current_agent
    
    def _should_rotate_agent(self) -> bool:
        """Determine if agent should be rotated"""
        if not self.current_agent:
            return True
        
        # Check usage count
        if self.current_agent_usage >= self.max_same_agent_usage:
            logger.debug("Rotating due to max usage count reached")
            return True
        
        # Check time interval
        time_since_rotation = datetime.now() - self.last_rotation_time
        if time_since_rotation.total_seconds() >= self.min_rotation_interval:
            logger.debug("Rotating due to time interval")
            return True
        
        # Check success rate
        if self.current_agent in self.database.user_agents:
            agent_info = self.database.user_agents[self.current_agent]
            if (agent_info.failure_count > 5 and 
                agent_info.success_rate < self.detection_threshold):
                logger.debug("Rotating due to low success rate")
                return True
        
        return False
    
    def _select_optimal_agent(self, preferred_category: Optional[UserAgentCategory] = None) -> str:
        """Select optimal user agent using weighted scoring"""
        candidates = self.database.get_all_agents()
        
        # Filter by category if specified
        if preferred_category:
            category_candidates = self.database.get_agents_by_category(preferred_category)
            if category_candidates:
                candidates = category_candidates
        
        # Remove recently used agents to avoid patterns
        available_candidates = [
            agent for agent in candidates 
            if not agent.is_recently_used or len(candidates) < 5
        ]
        
        if not available_candidates:
            available_candidates = candidates
        
        # Calculate scores for each candidate
        scored_candidates = []
        for agent in available_candidates:
            score = self._calculate_agent_score(agent)
            scored_candidates.append((agent, score))
        
        # Sort by score and add randomness to top candidates
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Select from top 30% with weighted randomness
        top_count = max(1, len(scored_candidates) // 3)
        top_candidates = scored_candidates[:top_count]
        
        # Weighted random selection from top candidates
        weights = [score for _, score in top_candidates]
        selected_agent = random.choices(top_candidates, weights=weights)[0][0]
        
        return selected_agent.agent_string
    
    def _calculate_agent_score(self, agent: UserAgentInfo) -> float:
        """Calculate score for agent selection"""
        score = 0.0
        
        # Popularity score
        score += agent.popularity_score * self.strategy_weights['popularity']
        
        # Success rate score (normalize to 0-1)
        success_rate_score = min(agent.success_rate / 100.0, 1.0) if agent.usage_count > 0 else 0.5
        score += success_rate_score * self.strategy_weights['success_rate']
        
        # Freshness score (prefer less recently used)
        if agent.last_used:
            hours_since_use = (datetime.now() - agent.last_used).total_seconds() / 3600
            freshness_score = min(hours_since_use / 24.0, 1.0)  # Normalize to 24 hours
        else:
            freshness_score = 1.0  # Never used = maximum freshness
        score += freshness_score * self.strategy_weights['freshness']
        
        # Random component
        score += random.random() * self.strategy_weights['randomness']
        
        return score
    
    def report_result(self, success: bool, detected: bool = False):
        """Report the result of using current user agent"""
        if self.current_agent:
            self.database.update_agent_stats(self.current_agent, success)
            
            if detected:
                self.stats.detection_incidents += 1
                logger.warning(f"Detection incident reported for agent: {self.current_agent[:50]}...")
    
    def get_rotation_stats(self) -> RotationStats:
        """Get rotation statistics"""
        # Update stats
        unique_agents = len(set(agent.agent_string for agent in self.database.get_all_agents() 
                               if agent.usage_count > 0))
        self.stats.unique_agents_used = unique_agents
        
        # Calculate category distribution
        category_dist = {}
        for agent in self.database.get_all_agents():
            if agent.usage_count > 0:
                cat = agent.category.value
                category_dist[cat] = category_dist.get(cat, 0) + agent.usage_count
        self.stats.category_distribution = category_dist
        
        # Calculate average success rate
        used_agents = [agent for agent in self.database.get_all_agents() if agent.usage_count > 0]
        if used_agents:
            avg_success = sum(agent.success_rate for agent in used_agents) / len(used_agents)
            self.stats.average_success_rate = avg_success
        
        return self.stats
    
    def reset_stats(self):
        """Reset all statistics"""
        self.stats = RotationStats()
        for agent in self.database.get_all_agents():
            agent.usage_count = 0
            agent.success_count = 0
            agent.failure_count = 0
            agent.last_used = None
