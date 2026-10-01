"""Shared MCP server using the official Streamable HTTP transport.

The genuine MCP endpoint is ``/mcp``. Student 3 connects to that endpoint
with the official SDK client. Plain JSON routes under ``/tools`` are retained
only so the existing Student 5 integration remains backward compatible; they
delegate to the same pure functions as the registered MCP tools.
"""

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from tools import check_customer_profile as _check_customer_profile
from tools import check_product_listing as _check_product_listing
from tools import check_review_quality as _check_review_quality

mcp = MCPServer("ASD Group 40 Shared MCP Server", version="1.1.0")

AVAILABLE_TOOLS = [
    "review_quality_check",
    "check_review_quality",
    "check_customer_profile",
    "check_product_listing",
]
TOOL_CONTRACTS = {
    "check_review_quality": {
        "description": "Deterministic moderation check for one product review.",
        "required": ["review_text", "rating"],
        "optional": ["existing_review_count", "average_rating"],
        "transport": "MCP and compatibility REST",
    },
    "check_customer_profile": {
        "description": "Privacy-minimised validation of one customer profile.",
        "required": [
            "loyalty_tier",
            "joined_at",
            "has_phone",
            "has_address",
            "as_of_date",
        ],
        "optional": [],
        "transport": "MCP",
    },
    "check_product_listing": {
        "description": "Read-only publish-readiness and price-position check for one product.",
        "required": ["sku", "name", "category", "price", "status"],
        "optional": [
            "description",
            "comparable_count",
            "comparable_avg_price",
            "comparable_min_price",
            "comparable_max_price",
        ],
        "transport": "MCP",
    },
}


@mcp.tool(name="check_review_quality", structured_output=True)
def check_review_quality(
    review_text: str,
    rating: int,
    existing_review_count: int = 0,
    average_rating: float | None = None,
) -> dict[str, Any]:
    """Check one product review for quality and moderation concerns."""
    return _check_review_quality(
        review_text, rating, existing_review_count, average_rating
    )


@mcp.tool(name="review_quality_check", structured_output=True)
def review_quality_check(
    review_text: str,
    rating: int,
    existing_review_count: int = 0,
    average_rating: float | None = None,
) -> dict[str, Any]:
    """Backward-compatible MCP name for Student 5's review tool."""
    return _check_review_quality(
        review_text, rating, existing_review_count, average_rating
    )


@mcp.tool(name="check_customer_profile", structured_output=True)
def check_customer_profile(
    loyalty_tier: str,
    joined_at: str,
    has_phone: bool,
    has_address: bool,
    as_of_date: str,
) -> dict[str, Any]:
    """Check tier, membership duration and optional profile completeness."""
    return _check_customer_profile(
        loyalty_tier, joined_at, has_phone, has_address, as_of_date
    )


@mcp.tool(name="check_product_listing", structured_output=True)
def check_product_listing(
    sku: str,
    name: str,
    category: str,
    price: float,
    status: str,
    description: str = "",
    comparable_count: int = 0,
    comparable_avg_price: float | None = None,
    comparable_min_price: float | None = None,
    comparable_max_price: float | None = None,
) -> dict[str, Any]:
    """Check one catalogue listing is ready to publish and how its price compares."""
    return _check_product_listing(
        sku, name, category, price, status, description,
        comparable_count, comparable_avg_price,
        comparable_min_price, comparable_max_price,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({
        "service": "mcp-server",
        "status": "ok",
        "protocol": "MCP Streamable HTTP",
        "endpoint": "/mcp",
        "tools": AVAILABLE_TOOLS,
    })


@mcp.custom_route("/tools", methods=["GET"])
async def list_compatibility_tools(_request: Request) -> JSONResponse:
    return JSONResponse({"tools": TOOL_CONTRACTS, "compatibility_rest": True})


@mcp.custom_route("/tools/check_review_quality", methods=["POST"])
async def review_quality_compatibility(request: Request) -> JSONResponse:
    """Compatibility REST path used by the existing Student 5 backend."""
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse(
            {"ok": False, "error": "request body must be an object"}, 400
        )
    if "review_text" not in payload or "rating" not in payload:
        return JSONResponse(
            {"ok": False, "error": "'review_text' and 'rating' are required"}, 400
        )
    result = _check_review_quality(
        review_text=payload.get("review_text"),
        rating=payload.get("rating"),
        existing_review_count=payload.get("existing_review_count", 0),
        average_rating=payload.get("average_rating"),
    )
    return JSONResponse({
        "ok": True,
        "tool": "check_review_quality",
        "result": result,
    })


def run():
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport != "streamable-http":
        raise ValueError("MCP_TRANSPORT must be 'stdio' or 'streamable-http'")

    port = int(os.getenv("SERVICE_PORT", "7002"))
    security = TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "host.docker.internal",
            "host.docker.internal:*",
        ],
        allowed_origins=[],
    )
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_BIND_ADDRESS", "0.0.0.0"),
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
