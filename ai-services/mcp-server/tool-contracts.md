# MCP Tool Contracts

Every tool is implemented once in `tools.py` as a pure, deterministic function
(no LLM call, no network call to another microservice).

* `server.py` is the native shared server. It uses the official `mcp==2.2.0`
  SDK and exposes genuine MCP Streamable HTTP at `http://localhost:7002/mcp`.
* The same server co-hosts the existing Student 5 plain REST route at
  `/tools/check_review_quality` for compatibility. That route is explicitly
  not MCP. `http_server.py` is a legacy Flask-only compatibility module.
* `mcp-config.json` selects stdio when an editor or other local MCP host starts
  `server.py` as a child process.

The MCP and compatibility routes call the same functions in `tools.py`.

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
- **Compatibility HTTP:** `POST /tools/check_review_quality` is co-hosted by
  `server.py`; the legacy `http_server.py` exposes the same route.
- **MCP tool names:** `review_quality_check` (the original Student 5 name)
  and `check_review_quality` (an equivalent descriptive alias) on `server.py`.

## check_customer_profile

- **Owner:** Student 3 - Customer Account Management
- **Purpose:** validate a privacy-minimised profile, calculate membership
  duration, and report missing optional fields.
- **Input:** `loyalty_tier`, ISO `joined_at`, booleans `has_phone` and
  `has_address`, and ISO `as_of_date`. The caller supplies `as_of_date` so the
  calculation is deterministic. Names and contact values are not accepted.
- **Output:** `tool`, `tier_valid`, nullable `membership_days`,
  `profile_status` (`complete`, `incomplete`, or `invalid`),
  `missing_optional_fields`, `warnings`, and structured `errors`.
- **Policy class:** read-only, deterministic, no side effects.
- **MCP tool name:** `check_customer_profile`.

## check_product_listing

- **Owner:** Student 1 - Product Catalogue
- **Purpose:** decide whether one catalogue listing is ready to publish
  (catalogue rules plus description and status readiness) and position its
  price against comparable products in the same category.
- **Input:** `sku`, `name`, `category` (`Audio`, `Computing`, `Home`,
  `Wearables`), `price` (1-9999), `status` (`active`, `draft`, `archived`) -
  all required; `description` (up to 1200 characters), `comparable_count`,
  `comparable_avg_price`, `comparable_min_price`, `comparable_max_price` -
  optional. The caller grounds the comparable facts from its own database
  (the other products in the category, excluding this one); the tool never
  reaches back into the catalogue service.
- **Output:** `tool`, `sku`, `listing_status` (`ready`, `needs_attention`,
  or `invalid`), `price_position` (`below_range`, `within_range`,
  `above_range`, `no_comparables`, or `unknown`), nullable
  `price_vs_average_pct`, `comparable_count`, `description_word_count`, and
  string lists `issues` (fix before publishing), `warnings` (informational)
  and `errors` (input contract violations).
- **Policy class:** read-only, deterministic, no side effects. The tool
  never writes a product, never changes a price and holds no database
  address or credential; the result is advice the administrator reviews.
- **MCP tool name:** `check_product_listing`.

## check_stock_reorder

- **Owner:** Student 4 - Inventory and Stock
- **Purpose:** determine whether one stock item is at or below its restock
  threshold and calculate a bounded reorder quantity.
- **Input:** `sku` (string), `quantity` (non-negative integer), and
  `restock_threshold` (non-negative integer). The caller supplies the values
  from its own database; the tool never reaches into the inventory service.
- **Output:** `tool`, `sku`, `reorder_required`, the validated quantity and
  threshold, `recommended_order_quantity` (null when no reorder is needed,
  otherwise 10-1000), `reason`, and `errors`.
- **Policy class:** read-only, deterministic, no side effects. The suggested
  quantity targets twice the threshold, bounded to the configured order range.
- **MCP tool name:** `check_stock_reorder`.

## Adding your own tool

1. Add a pure function to `tools.py` (grounding facts as arguments, no calls
   to other microservices).
2. Register it with an exact explicit name using `@mcp.tool()` in `server.py`.
3. Add a compatibility REST route only when an existing non-MCP consumer
   requires one; new integrations must use `/mcp`.
4. Document the contract here, following the shape above.
5. Add tests to `tests/test_tools.py` (pure function) and
   `tests/test_http_server.py` (HTTP route) - both run offline, no LLM
   or other microservice required.
