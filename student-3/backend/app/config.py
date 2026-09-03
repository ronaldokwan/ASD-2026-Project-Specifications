"""Environment-based configuration for the Student 3 backend."""

import os


class Config:
    SERVICE_NAME = "student-3-backend"
    STUDENT = 3
    OWNER = "Vishvak Ananthakrishnan Rameshkumar"
    FEATURE = "Customer Account Management"

    DATABASE_URL = os.getenv("DATABASE_URL", "http://student-3-db:9003").rstrip("/")
    DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "10"))
    AI_MODE_URL = os.getenv("AI_MODE_URL", "http://ai-mode:7000").rstrip("/")
    AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    PORT = int(os.getenv("SERVICE_PORT", "8003"))

    LOYALTY_TIERS = ("Bronze", "Silver", "Gold")
    REWARD_MIN_WORDS = 3
    REWARD_MAX_WORDS = 20
    REASON_MIN_WORDS = 5
    REASON_MAX_WORDS = 40
