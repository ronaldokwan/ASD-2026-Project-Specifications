"""Thin client for the Ollama runtime.

Identical in shape to ai-services/ai-mode/agent/ollama_client.py. Each shared
AI service keeps its own copy so it can be started, tested and deployed as an
independent process - this one just happens to also be the Multi-Agent
Server's only path to the LLM.
"""

import os

import requests


class OllamaError(RuntimeError):
    """Raised when the Ollama runtime is unreachable or returns an error."""


class OllamaClient:
    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (
            base_url or os.getenv("OLLAMA_URL", "http://ollama:11434")
        ).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "qwen2.5:3b")
        self.timeout = int(timeout or os.getenv("LLM_TIMEOUT", "120"))

    # -- health ------------------------------------------------------------
    def available_models(self):
        """Return the list of model tags currently pulled into the runtime."""
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=10)
            res.raise_for_status()
            return [m.get("name", "") for m in res.json().get("models", [])]
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama unreachable at {self.base_url}: {exc}") from exc

    def is_ready(self):
        try:
            return any(
                m.split(":")[0] == self.model.split(":")[0]
                for m in self.available_models()
            )
        except OllamaError:
            return False

    # -- generation --------------------------------------------------------
    def generate(self, prompt, system=None, json_mode=True, temperature=0.4):
        """Send one prompt to the LLM and return the raw text response."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_mode:
            # Ask Ollama to constrain decoding to valid JSON.
            payload["format"] = "json"

        try:
            res = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
            res.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"LLM call failed ({self.model}): {exc}") from exc

        return (res.json().get("response") or "").strip()
