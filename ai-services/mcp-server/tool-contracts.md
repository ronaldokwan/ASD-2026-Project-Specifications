# MCP Tool Contracts

Every tool is implemented once in `tools.py` as a pure, deterministic function
(no LLM call, no network call to another microservice) and exposed two ways:

* `server.py` - the real Model Context Protocol server (stdio transport, via
  the official `mcp` SDK's `FastMCP`). Launch it with any MCP-aware client
  using `mcp-config.json` (Claude Desktop, the VS Code MCP extension, `mcp
  dev server.py`, etc.) to list and call tools interactively.
* `http_server.py` - a plain Flask HTTP front door on port **7002**. This is
  the "shared non-containerised local MCP server" every student backend
  actually calls over the network at request time, since a synchronous Flask
  request handler isn't a good fit for the MCP stdio transport.

Both front doors call the same function, so there is only one place tool
behaviour can drift.

## check_review_quality

- **Owner:** Student 5 - Reviews and Ratings
- **Purpose:** deterministic moderation check for one product review (spam
  language, links, reviews too short to be useful, star rating vs. text
  sentiment mismatch).
- **Input:** `review_text` (string, required), `rating` (1-5, required),
  `existing_review_count` (int, optional), `average_rating` (number,
  optional). The caller grounds the tool with `existing_review_count` /
  `average_rating` pulled from its own database - the tool never reaches
  back into another service.
- **Output:** `{"flagged": bool, "reasons": [string, ...], "spam_score":
  0.0-1.0, "duplicate_risk": "low"|"possible", "word_count": int}`
- **Policy class:** read-only, no side effects.
- **HTTP:** `POST /tools/check_review_quality` on `http_server.py`.
- **MCP tool name:** `review_quality_check` on `server.py`.

## check_order_fulfilment

- **Owner:** Student 2 - Customer Orders
- **Purpose:** deterministic shipment-readiness check grounded with facts from
  the caller's order record.
- **Input:** `order_number` (string), `status` (string), `line_count` (int),
  `total_quantity` (int), `order_total` (number), and `inventory_committed`
  (boolean). All fields are required.
- **Output:** `{"ready_to_ship": bool, "blockers": [string, ...],
  "checked_rules": [string, ...], "summary": string}`.
- **Policy class:** read-only, no side effects. The tool never reads another
  service and never calls an LLM.
- **HTTP:** `POST /tools/check_order_fulfilment` on `http_server.py`.
- **MCP tool name:** `check_order_fulfilment` on `server.py`.

## Adding your own tool

1. Add a pure function to `tools.py` (grounding facts as arguments, no calls
   to other microservices).
2. Register it with `@mcp.tool()` in `server.py`.
3. Add a matching `POST /tools/<name>` route in `http_server.py`, and an
   entry in its `TOOL_CONTRACTS` dict.
4. Document the contract here, following the shape above.
5. Add tests to `tests/test_tools.py` (pure function) and
   `tests/test_http_server.py` (HTTP route) - both run offline, no LLM
   or other microservice required.
