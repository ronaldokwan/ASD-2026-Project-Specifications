"""Student 3 Customer Account Management backend package."""

from flask import Flask

from .config import Config


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    from .routes import api
    app.register_blueprint(api)
    return app


__all__ = ["create_app", "Config"]
