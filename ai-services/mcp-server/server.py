"""The shared MCP server, speaking the real Model Context Protocol.

Runs over stdio (the SDK's default transport) so any MCP-aware client - the
Claude Desktop / VS Code MCP extension, `mcp dev`, or a teammate's own script
- can list and call these tools directly, using ``mcp-config.json``.

Student backends that need a tool result inside an HTTP request/response
cycle do not talk to this process: they call ``http_server.py`` instead,
which wraps the exact same functions in ``tools.py`` behind plain HTTP JSON
endpoints. Both front doors share one implementation so there is only one
place tool logic can drift.

Run standalone:  python server.py
"""

from mcp.server.fastmcp import FastMCP

from tools import check_order_fulfilment as evaluate_order_fulfilment
from tools import check_review_quality

mcp = FastMCP("ASD Group 40 Shared MCP Server")

AVAILABLE_TOOLS = ["check_review_quality", "check_order_fulfilment"]


@mcp.tool()
def review_quality_check(review_text: str, rating: int, existing_review_count: int = 0,
                          average_rating: float = None):
    """Moderation check for one product review (Student 5 - Reviews and Ratings)."""
    return check_review_quality(review_text, rating, existing_review_count, average_rating)


@mcp.tool()
def check_order_fulfilment(
    order_number: str,
    status: str,
    line_count: int,
    total_quantity: int,
    order_total: float,
    inventory_committed: bool,
):
    """Check whether an order is ready to ship (Student 2 - Customer Orders)."""
    return evaluate_order_fulfilment(
        order_number,
        status,
        line_count,
        total_quantity,
        order_total,
        inventory_committed,
    )


if __name__ == "__main__":
    print("Starting the shared MCP server (Group 40)...")
    print("Server status: RUNNING")
    print("Available tools:")
    for tool in AVAILABLE_TOOLS:
        print("- {}".format(tool))
    mcp.run()
