"""Run the shared native Multi-Agent Server."""

import os

from service import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7004")), threaded=True)
