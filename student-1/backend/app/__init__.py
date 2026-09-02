"""Student 1 - Product Catalogue - BACKEND/API microservice (Flask)."""

from flask import Flask

from .config import Config


def create_app(config_object=Config):
    """Application factory - lets the tests build an app without gunicorn."""
    app = Flask(__name__)
    app.config.from_object(config_object)

    from .routes import api
    app.register_blueprint(api)

    return app


__all__ = ["create_app", "Config"]
