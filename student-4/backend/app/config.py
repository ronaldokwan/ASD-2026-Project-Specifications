"""Configuration for the Inventory and Stock backend/API microservice.

Every value comes from the environment so the same image runs unchanged on any
machine that starts the stack with Docker Compose.
"""

import os


def _enabled(name, default="true"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SERVICE_NAME = "student-4-backend"
    STUDENT = 4
    OWNER = "Jonathan Czesler"
    FEATURE = "Inventory and Stock"

    # Student 4 database microservice.
    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-4-db:9004").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))

    # Shared AI-Mode service (Plan -> Act -> Observe -> Adapt over Ollama).
    AI_MODE_URL = os.getenv("AI_MODE_URL", "http://ai-mode:7000").rstrip("/")
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")

    # Shared services run on the host; Compose supplies reachable URLs to this container.
    MCP_SERVER_URL = os.getenv(
        "MCP_SERVER_URL", "http://host.docker.internal:7002"
    ).rstrip("/")
    MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "15"))
    MCP_ENABLED = _enabled("MCP_ENABLED")
    MCP_TOOL = "check_stock_reorder"

    RAG_SERVER_URL = os.getenv(
        "RAG_SERVER_URL", "http://host.docker.internal:7003"
    ).rstrip("/")
    RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "120"))
    RAG_ENABLED = _enabled("RAG_ENABLED")
    # Tag documents and filter retrieval so inventory questions cannot cite other features.
    RAG_FEATURE = "inventory_stock"
    RAG_TOP_K = 5
    QUESTION_MIN_CHARS = 5
    QUESTION_MAX_CHARS = 500

    PORT = int(os.getenv("SERVICE_PORT", "8004"))

    # Business rules for inventory management, enforced on every write.
    QUANTITY_MIN = 0
    QUANTITY_MAX = 999999
    RESTOCK_THRESHOLD_MIN = 0
    RESTOCK_THRESHOLD_MAX = 999999
    VALID_STOCK_LEVELS = ("good", "low")
    RECOMMENDATION_MIN_ORDER = 10
    RECOMMENDATION_MAX_ORDER = 1000
