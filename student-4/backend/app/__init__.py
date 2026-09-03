"""Student 4 - Inventory and Stock - BACKEND/API microservice (Flask)."""

from flask import Flask

from .config import Config


def create_app(config_object=Config):
    """Application factory - lets the tests build an app without gunicorn."""
    app = Flask(__name__)
    # Load service-wide settings before registering routes that use them.
    app.config.from_object(config_object)

    from .routes import api
    # Keep all HTTP endpoints in one blueprint so the app factory stays small.
    app.register_blueprint(api)

    return app


__all__ = ["create_app", "Config"]
