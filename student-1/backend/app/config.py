"""Configuration for the Product Catalogue backend/API microservice.

Every value comes from the environment so the same image runs unchanged on any
machine that starts the stack with Docker Compose.
"""

import os


class Config:
    SERVICE_NAME = "student-1-backend"
    STUDENT = 1
    OWNER = "Ronaldo Kwan"
    FEATURE = "Product Catalogue"

    # Student 1 database microservice.
    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-1-db:9001").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))

    # Shared AI-Mode service (Plan -> Act -> Observe -> Adapt over Ollama).
    AI_MODE_URL = os.getenv("AI_MODE_URL", "http://ai-mode:7000").rstrip("/")
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")

    PORT = int(os.getenv("SERVICE_PORT", "8001"))

    # Business rules for the catalogue, enforced on every write and used as the
    # Observe guardrails for AI-generated values.
    VALID_STATUSES = ("active", "draft", "archived")
    VALID_CATEGORIES = ("Audio", "Computing", "Home", "Wearables")
    PRICE_MIN = 1.0
    PRICE_MAX = 9999.0
    DESCRIPTION_MIN_WORDS = 20
    DESCRIPTION_MAX_WORDS = 60
