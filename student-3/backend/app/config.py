"""Environment-based configuration for the Student 3 backend."""

import os


def _enabled(name, default="true"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SERVICE_NAME = "student-3-backend"
    STUDENT = 3
    OWNER = "Vishvak Ananthakrishnan Rameshkumar"
    FEATURE = "Customer Account Management"

    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-3-db:9003").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))
    AI_MODE_URL = os.getenv(
        "AI_MODE_URL", "http://host.docker.internal:7001"
    ).rstrip("/")
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    AI_MODE_ENABLED = _enabled("AI_MODE_ENABLED")

    MCP_SERVER_URL = os.getenv(
        "MCP_SERVER_URL", "http://host.docker.internal:7002"
    ).rstrip("/")
    MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "15"))
    MCP_ENABLED = _enabled("MCP_ENABLED")

    RAG_SERVER_URL = os.getenv(
        "RAG_SERVER_URL", "http://host.docker.internal:7003"
    ).rstrip("/")
    RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "120"))
    RAG_ENABLED = _enabled("RAG_ENABLED")
    PORT = int(os.getenv("SERVICE_PORT", "8003"))

    LOYALTY_TIERS = ("Bronze", "Silver", "Gold")
    REWARD_MIN_WORDS = 3
    REWARD_MAX_WORDS = 20
    REASON_MIN_WORDS = 5
    REASON_MAX_WORDS = 40
