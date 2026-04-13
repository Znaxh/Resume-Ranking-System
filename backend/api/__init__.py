"""API package for Resume Ranking System"""

from .routes import create_routes, get_routes_blueprint
from .middleware import setup_middleware
from .error_handlers import register_error_handlers

__all__ = [
    'create_routes',
    'get_routes_blueprint',
    'setup_middleware',
    'register_error_handlers',
]
