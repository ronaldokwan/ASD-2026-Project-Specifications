"""Client for the shared MCP stock reorder assessment tool."""

import asyncio
import time

import requests
from mcp import Client

from .config import Config


class MCPServiceUnavailable(RuntimeError):
    """The MCP server is disabled, timed out or unreachable."""


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
        # Flask routes are synchronous, so run the MCP SDK's async call to completion here.
        return asyncio.run(
            asyncio.wait_for(_call_tool(arguments), timeout=Config.MCP_TIMEOUT)
        )
    except TimeoutError as exc:
        raise MCPServiceUnavailable("MCP reorder check timed out") from exc
    except MCPBadResponse:
        raise
    except Exception as exc:
        raise MCPServiceUnavailable(
            "MCP server is unreachable at {}".format(_endpoint())
        ) from exc


def _validate_result(result, sku):
    # Treat the tool response as an external contract, not as trusted application data.
    if not isinstance(result, dict):
        raise MCPBadResponse("MCP result must be an object")
    if result.get("tool") != Config.MCP_TOOL or result.get("sku") != sku.upper():
        raise MCPBadResponse("MCP result identifies the wrong tool or SKU")
    if type(result.get("reorder_required")) is not bool:
        raise MCPBadResponse("MCP reorder_required must be a boolean")
    quantity = result.get("recommended_order_quantity")
    if quantity is not None and (type(quantity) is not int or quantity < 1):
        raise MCPBadResponse("MCP recommended_order_quantity must be a positive integer or null")
    errors = result.get("errors")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        raise MCPBadResponse("MCP errors must be a list of strings")
    return result


def check_reorder(stock):
    """Assess a stock record without passing unrelated inventory fields."""
    if not Config.MCP_ENABLED:
        raise MCPServiceUnavailable("MCP integration is disabled")
    # Send only the tool's declared inputs; unrelated stock details stay in this service.
    arguments = {
        "sku": stock["sku"],
        "quantity": stock["quantity"],
        "restock_threshold": stock["restock_threshold"],
    }
    started = time.time()
    result = _validate_result(_execute(arguments), arguments["sku"])
    return {
        "tool": Config.MCP_TOOL,
        "server": _endpoint(),
        "stock_id": stock["id"],
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