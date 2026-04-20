"""Watchdog App Factory."""

import os
from flask import Flask
from app.database import init_db


def create_app(config=None):
    """Create and configure Flask application.

    Args:
        config: Optional configuration dict

    Returns:
        Configured Flask app instance
    """
    app = Flask(__name__, instance_relative_config=True)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Default configuration
    app.config.setdefault('DATABASE', os.path.join(app.instance_path, 'watchdog.db'))
    
    if config:
        app.config.update(config)
    
    # Initialize database
    init_db(app)
    
    # Register blueprints
    from app.api import api_bp
    from app.dashboard import dashboard_bp
    from app.admin import admin_bp
    
    app.register_blueprint(api_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    
    # Initialize scheduler
    from app.scheduler import init_scheduler
    init_scheduler(app)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return {"error": "Not found"}, 404
    
    @app.errorhandler(500)
    def server_error(error):
        """Handle 500 errors."""
        return {"error": "Internal server error"}, 500
    
    return app
