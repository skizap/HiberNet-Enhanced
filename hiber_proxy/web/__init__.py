"""
Web interface components for HiberProxy Enhanced

Provides Flask-based web interface with dark orange terminal aesthetic
for proxy management, configuration, and analytics.
"""

from .app import create_app

__all__ = ['create_app']
