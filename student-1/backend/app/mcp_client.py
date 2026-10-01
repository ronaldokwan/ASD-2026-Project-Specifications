"""Client for the shared MCP server - the Product Catalogue's listing check.

frontend -> backend/API -> shared MCP server (/mcp) -> check_product_listing

"""

import asyncio
import time

import requests
from mcp import Client

from . import db_client
from .config import Config

_RESULT_LISTS = ("issues", "warnings", "errors")
_LISTING_STATUSES = ("ready", "needs_attention", "invalid")
_PRICE_POSITIONS = (
    "below_range",
    "within_range",
    "above_range",
    "no_comparables",
    "unknown",
)


class MCPServiceUnavailable(RuntimeError):
    """The shared MCP server is disabled, timed out or unreachable."""


class MCPBadResponse(RuntimeError):
    """The MCP server returned a failed or malformed tool result."""


def _endpoint():
    return "{}/mcp".format(Config.MCP_SERVER_URL)


# ----------------------------------------------------------------- grounding
def build_arguments(product):
    """Tool arguments for one product, grounded in the rest of its category."""
    others = [
        row
        for row in db_client.list_products(category=product["category"])
        if row["id"] != product["id"]
    ]
    prices = [float(row["price"]) for row in others]
    arguments = {
        "sku": product["sku"],
        "name": product["name"],
        "category": product["category"],
        "price": float(product["price"]),
        "status": product["status"],
        "description": product.get("description") or "",
        "comparable_count": len(prices),
    }
    if prices:
        arguments["comparable_avg_price"] = round(sum(prices) / len(prices), 2)
        arguments["comparable_min_price"] = min(prices)
        arguments["comparable_max_price"] = max(prices)
    return arguments


# ------------------------------------------------------------------ transport
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
        raise MCPServiceUnavailable("MCP listing check timed out") from exc
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
    if result.get("tool") != Config.MCP_TOOL:
        raise MCPBadResponse("MCP result names the wrong tool")
    if result.get("listing_status") not in _LISTING_STATUSES:
        raise MCPBadResponse("MCP listing_status is invalid")
    if result.get("price_position") not in _PRICE_POSITIONS:
        raise MCPBadResponse("MCP price_position is invalid")
    pct = result.get("price_vs_average_pct")
    if pct is not None and (isinstance(pct, bool) or not isinstance(pct, (int, float))):
        raise MCPBadResponse("MCP price_vs_average_pct must be a number or null")
    for field in ("comparable_count", "description_word_count"):
        value = result.get(field)
        if type(value) is not int or value < 0:
            raise MCPBadResponse("MCP {} must be a non-negative integer".format(field))
    for field in _RESULT_LISTS:
        items = result.get(field)
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise MCPBadResponse("MCP {} must be a list of strings".format(field))
    return result


# ---------------------------------------------------------------------- public
def check_listing(product):
    """Run the shared MCP listing check for one catalogue product."""
    if not Config.MCP_ENABLED:
        raise MCPServiceUnavailable("MCP integration is disabled")
    arguments = build_arguments(product)
    started = time.time()
    result = _validate_result(_execute(arguments))
    return {
        "tool": Config.MCP_TOOL,
        "server": _endpoint(),
        "product_id": product["id"],
        "arguments": arguments,
        "result": result,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def health():
    if not Config.MCP_ENABLED:
        return {"status": "disabled"}
    try:
        response = requests.get(
            "{}/health".format(Config.MCP_SERVER_URL), timeout=(1, 2)
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
