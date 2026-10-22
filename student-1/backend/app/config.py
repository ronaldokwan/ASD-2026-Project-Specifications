"""Configuration for the Product Catalogue backend/API microservice.

Every value comes from the environment so the same image runs unchanged on any
machine that starts the stack with Docker Compose.
"""

import os


def _enabled(name, default="true"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SERVICE_NAME = "student-1-backend"
    STUDENT = 1
    OWNER = "Ronaldo Kwan"
    FEATURE = "Product Catalogue"

    # Student 1 database microservice.
    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-1-db:9001").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))

    # Shared AI-Mode service (Plan -> Act -> Observe -> Adapt over Ollama).
    AI_MODE_URL = os.getenv("AI_MODE_URL", "http://host.docker.internal:7001").rstrip(
        "/"
    )
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    AI_MODE_ENABLED = _enabled("AI_MODE_ENABLED")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")

    MCP_SERVER_URL = os.getenv(
        "MCP_SERVER_URL", "http://host.docker.internal:7002"
    ).rstrip("/")
    MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "15"))
    MCP_ENABLED = _enabled("MCP_ENABLED")
    MCP_TOOL = "check_product_listing"

    RAG_SERVER_URL = os.getenv(
        "RAG_SERVER_URL", "http://host.docker.internal:7003"
    ).rstrip("/")
    RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "120"))
    RAG_ENABLED = _enabled("RAG_ENABLED")
    RAG_FEATURE = "product_catalogue"
    RAG_TOP_K = 5
    QUESTION_MIN_CHARS = 5
    QUESTION_MAX_CHARS = 500

    PORT = int(os.getenv("SERVICE_PORT", "8001"))

    # Business rules for the catalogue, enforced on every write and used as the
    # Observe guardrails for AI-generated values.
    VALID_STATUSES = ("active", "draft", "archived")
    # Catalogue lands on the rows that changed most recently.
    DEFAULT_SORT = "latest"
    VALID_CATEGORIES = ("Audio", "Computing", "Home", "Wearables")
    PRICE_MIN = 1.0
    PRICE_MAX = 9999.0
    DESCRIPTION_MIN_WORDS = 20
    DESCRIPTION_MAX_WORDS = 60
