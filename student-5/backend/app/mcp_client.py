"""HTTP client for the shared MCP server (ai-services/mcp-server).

Reviews and Ratings uses the ``check_review_quality`` tool it contributed to
the shared server for a moderation check on a new review, before asking
AI-Mode to double-check the tool's verdict (see ai_agent.py:validate_mcp_result).
"""

import requests

from .config import Config


class MCPServiceError(RuntimeError):
    """The shared MCP server could not be reached."""


def check_review_quality(review_text, rating, existing_review_count=0, average_rating=None):
    url = "{}/tools/check_review_quality".format(Config.MCP_SERVER_URL)
    payload = {
        "review_text": review_text,
        "rating": rating,
        "existing_review_count": existing_review_count,
        "average_rating": average_rating,
    }
    try:
        response = requests.post(url, json=payload, timeout=Config.MCP_TIMEOUT)
    except requests.RequestException as exc:
        raise MCPServiceError("MCP server unreachable at {}: {}".format(url, exc)) from exc

    if response.status_code >= 400:
        raise MCPServiceError("MCP server returned {}: {}".format(response.status_code, response.text))

    try:
        return response.json()
    except ValueError as exc:
        raise MCPServiceError("MCP server returned a non-JSON response") from exc
