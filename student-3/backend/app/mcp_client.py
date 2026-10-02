"""Real MCP Streamable HTTP client for Student 3's profile tool."""

import asyncio
from datetime import date

from mcp import Client

from .config import Config


class MCPServiceUnavailable(RuntimeError):
    """The shared MCP service is disabled, timed out or unreachable."""


class MCPBadResponse(RuntimeError):
    """The MCP service returned a malformed or failed tool result."""


def _mcp_endpoint():
    return "{}/mcp".format(Config.MCP_SERVER_URL)


async def _call_tool(arguments):
    async with Client(
        _mcp_endpoint(), read_timeout_seconds=Config.MCP_TIMEOUT
    ) as client:
        response = await client.call_tool("check_customer_profile", arguments)
        if response.is_error:
            raise MCPBadResponse("check_customer_profile returned a tool error")
        return response.structured_content


def _execute(arguments):
    try:
        return asyncio.run(
            asyncio.wait_for(_call_tool(arguments), timeout=Config.MCP_TIMEOUT)
        )
    except TimeoutError as exc:
        raise MCPServiceUnavailable("MCP profile check timed out") from exc
    except MCPBadResponse:
        raise
    except Exception as exc:
        raise MCPServiceUnavailable(
            "MCP server is unreachable at {}".format(_mcp_endpoint())
        ) from exc


def _validate_result(result):
    if not isinstance(result, dict):
        raise MCPBadResponse("MCP result must be an object")
    required = {
        "tool", "tier_valid", "membership_days", "profile_status",
        "missing_optional_fields", "warnings", "errors",
    }
    if not required.issubset(result):
        raise MCPBadResponse("MCP result is missing required fields")
    if result["tool"] != "check_customer_profile":
        raise MCPBadResponse("MCP result names the wrong tool")
    if type(result["tier_valid"]) is not bool:
        raise MCPBadResponse("MCP tier_valid must be a boolean")
    days = result["membership_days"]
    if days is not None and (type(days) is not int or days < 0):
        raise MCPBadResponse("MCP membership_days must be a non-negative integer or null")
    if result["profile_status"] not in ("complete", "incomplete", "invalid"):
        raise MCPBadResponse("MCP profile_status is invalid")
    for field in ("missing_optional_fields", "warnings", "errors"):
        if not isinstance(result[field], list) or not all(
            isinstance(item, str) for item in result[field]
        ):
            raise MCPBadResponse("MCP {} must be a list of strings".format(field))
    return {key: result[key] for key in required}


def check_customer_profile(customer, as_of_date=None):
    """Ground the tool without sending customer identity or contact values."""
    if not Config.MCP_ENABLED:
        raise MCPServiceUnavailable("MCP integration is disabled")
    arguments = {
        "loyalty_tier": customer.get("loyalty_tier"),
        "joined_at": customer.get("joined_at"),
        "has_phone": bool(customer.get("phone")),
        "has_address": bool(customer.get("address")),
        "as_of_date": as_of_date or date.today().isoformat(),
    }
    return _validate_result(_execute(arguments))
