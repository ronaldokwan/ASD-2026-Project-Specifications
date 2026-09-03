"""Configuration for the Reviews and Ratings backend/API microservice.

Every value comes from the environment so the same image runs unchanged on any
machine that starts the stack with Docker Compose.
"""

import os


class Config:
    SERVICE_NAME = "student-5-backend"
    STUDENT = 5
    OWNER = "Alexander McGuinn"
    FEATURE = "Reviews and Ratings"

    # Student 5 database microservice.
    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-5-db:9005").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))

    # Student 1's Product Catalogue API - used only to look up a product's name
    # from its SKU so reviews are easier to read. A best-effort call: if the
    # catalogue is unreachable, callers fall back to showing the raw SKU.
    CATALOGUE_URL = os.getenv("CATALOGUE_URL", "http://student-1-backend:8001").rstrip("/")
    CATALOGUE_TIMEOUT = int(os.getenv("CATALOGUE_TIMEOUT", "5"))

    # Shared AI-Mode service (Plan -> Act -> Observe -> Adapt over Ollama).
    AI_MODE_URL = os.getenv("AI_MODE_URL", "http://ai-mode:7000").rstrip("/")
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")

    PORT = int(os.getenv("SERVICE_PORT", "8005"))

    # Business rules for reviews, enforced on every write and used as the
    # Observe guardrails for the AI-generated pros/cons summary.
    RATING_MIN = 1
    RATING_MAX = 5
    REVIEW_MIN_CHARS = 5
    REVIEW_MAX_CHARS = 1000
    SUMMARY_MIN_WORDS = 8
    SUMMARY_MAX_WORDS = 40
