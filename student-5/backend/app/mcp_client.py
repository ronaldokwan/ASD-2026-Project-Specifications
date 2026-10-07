"""Real MCP Streamable HTTP client for the shared MCP server (ai-services/mcp-server).

Reviews and Ratings uses the ``check_review_quality`` tool it contributed to
the shared server for a moderation check on a new review, before asking
AI-Mode to double-check the tool's verdict (see ai_agent.py:validate_mcp_result).
"""

import asyncio
import time

import requests
from mcp import Client

from .config import Config

_DUPLICATE_RISKS = ("low", "possible")


class MCPServiceUnavailable(RuntimeError):
    """The shared MCP server is disabled, timed out or unreachable."""


class MCPBadResponse(RuntimeError):
    """The MCP server returned a failed or malformed tool result."""


def _endpoint():
    return "{}/mcp".format(Config.MCP_SERVER_URL)


async def _call_tool(arguments):
    async with Client(_endpoint(), read_timeout_seconds=Config.MCP_TIMEOUT) as client:
        response = await client.call_tool(Config.MCP_TOOL, arguments)
        if response.is_error:
            raise MCPBadResponse("{} returned a tool error".format(Config.MCP_TOOL))
        return response.structured_content


def _execute(arguments):
    try:
        return asyncio.run(
            asyncio.wait_for(_call_tool(arguments), timeout=Config.MCP_TIMEOUT)
        )
    except TimeoutError as exc:
        raise MCPServiceUnavailable("MCP review quality check timed out") from exc
    except MCPBadResponse:
        raise
    except Exception as exc:
        raise MCPServiceUnavailable(
            "MCP server is unreachable at {}".format(_endpoint())
        ) from exc


def _validate_result(result):
    """Accept only a result that matches the tool contract in tool-contracts.md."""
    if not isinstance(result, dict):
        raise MCPBadResponse("MCP result must be an object")
    if type(result.get("flagged")) is not bool:
        raise MCPBadResponse("MCP flagged must be a boolean")
    reasons = result.get("reasons")
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise MCPBadResponse("MCP reasons must be a list of strings")
    spam_score = result.get("spam_score")
    if isinstance(spam_score, bool) or not isinstance(spam_score, (int, float)):
        raise MCPBadResponse("MCP spam_score must be a number")
    if not 0.0 <= spam_score <= 1.0:
        raise MCPBadResponse("MCP spam_score must be between 0.0 and 1.0")
    if result.get("duplicate_risk") not in _DUPLICATE_RISKS:
        raise MCPBadResponse("MCP duplicate_risk is invalid")
    word_count = result.get("word_count")
    if type(word_count) is not int or word_count < 0:
        raise MCPBadResponse("MCP word_count must be a non-negative integer")
    return result


def check_review_quality(review_text, rating, existing_review_count=0, average_rating=None):
    """Run the shared MCP moderation check for one review."""
    if not Config.MCP_ENABLED:
        raise MCPServiceUnavailable("MCP integration is disabled")
    arguments = {
        "review_text": review_text,
        "rating": rating,
        "existing_review_count": existing_review_count,
        "average_rating": average_rating,
    }
    started = time.time()
    result = _validate_result(_execute(arguments))
    return {
        "tool": Config.MCP_TOOL,
        "server": _endpoint(),
        "arguments": arguments,
        "result": result,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def health():
    if not Config.MCP_ENABLED:
        return {"status": "disabled"}
    try:
        response = requests.get("{}/health".format(Config.MCP_SERVER_URL), timeout=(1, 2))
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
