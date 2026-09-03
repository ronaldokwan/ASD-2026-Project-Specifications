"""WSGI entry point for the Student 3 backend service."""

import os

from app import Config, create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", str(Config.PORT))), debug=True)
