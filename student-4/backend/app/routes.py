"""REST API for the Inventory and Stock (Student 4).

Endpoints registered in the Project Group Registration Form:

    GET    /api/stock               list + filter (?sku= ?category= ?stock_level= ?search= ?sort=)
    POST   /api/stock               create
    GET    /api/stock/<id>          read one
    PUT    /api/stock/<id>          update
    DELETE /api/stock/<id>          delete
    GET    /api/stock/low           low-stock items (qty <= restock_threshold)
    POST   /api/stock/recommend     AI restock recommendation

Plus supporting endpoints: GET /health.
"""

from flask import Blueprint, jsonify, request

from . import ai_agent, db_client, mcp_client, rag_client
from .config import Config
from .validation import ValidationError, clean_stock

api = Blueprint("api", __name__)


# --------------------------------------------------------------------- meta
@api.get("/health")
def health():
    """Report this service's health and its database and AI dependencies."""
    try:
        database = db_client.health()
        database_ok = True
    except db_client.DatabaseError as exc:
        database, database_ok = {"error": str(exc)}, False

    body = {
        "service": Config.SERVICE_NAME,
        "student": Config.STUDENT,
        "owner": Config.OWNER,
        "feature": Config.FEATURE,
        "status": "ok" if database_ok else "degraded",
        "database": database,
        "ai_mode": ai_agent.ai_mode_health(),
        "mcp_server": mcp_client.health(),
        "rag_server": rag_client.health(),
    }
    return jsonify(body), (200 if database_ok else 503)


@api.get("/api/stock")
def list_stock():
    """List stock records and pass permitted query filters downstream."""
    stock = db_client.list_stock(
        sku=request.args.get("sku"),
        category=request.args.get("category"),
        stock_level=request.args.get("stock_level"),
        search=request.args.get("search"),
        sort=request.args.get("sort", "name"),
    )
    return jsonify({"count": len(stock), "stock": stock})


@api.get("/api/stock/low")
def list_low_stock():
    """Return items below restock threshold."""
    low = db_client.list_low_stock()
    return jsonify({"count": len(low), "low_stock": low})


@api.get("/api/stock/<int:stock_id>")
def get_stock(stock_id):
    """Return one stock record by its internal identifier."""
    return jsonify(db_client.get_stock(stock_id))


@api.post("/api/stock")
def create_stock():
    """Validate a complete stock payload and create the record."""
    payload = clean_stock(request.get_json(silent=True) or {})
    stock = db_client.create_stock(payload)
    # Keep the derived search index current, while the client makes this best-effort.
    rag_client.sync_stock(stock)
    return jsonify(stock), 201


@api.put("/api/stock/<int:stock_id>")
def update_stock(stock_id):
    """Validate only supplied fields and update the matching record."""
    payload = clean_stock(request.get_json(silent=True) or {}, partial=True)
    stock = db_client.update_stock(stock_id, payload)
    # Upsert uses the same stable document ID as creation.
    rag_client.sync_stock(stock)
    return jsonify(stock)


@api.delete("/api/stock/<int:stock_id>")
def delete_stock(stock_id):
    """Delete a stock record and return its identifier for client updates."""
    db_client.delete_stock(stock_id)
    rag_client.remove_stock(stock_id)
    return jsonify({"deleted": stock_id})


# ------------------------------------------------------------------- AI-mode
@api.post("/api/stock/recommend")
def recommend_restocking():
    """Request AI restock recommendation for low inventory items."""
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "")).strip()
    
    errors = []
    if len(category) < 2:
        errors.append("category is required (at least 2 characters)")
    if errors:
        raise ValidationError(errors)

    outcome = ai_agent.recommend_restocking(category)
    return jsonify(outcome), (200 if outcome.get("ok") else 502)


# ----------------------------------------------------------- shared MCP / RAG
@api.post("/api/stock/<int:stock_id>/mcp-check")
def mcp_stock_check(stock_id):
    """Run the shared deterministic reorder assessment for one stock item."""
    # The frontend calls this API route; only the backend talks to MCP.
    stock = db_client.get_stock(stock_id)
    return jsonify(mcp_client.check_reorder(stock))


@api.post("/api/stock/ask")
def ask_inventory():
    """Answer a question using the inventory-scoped RAG corpus."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])
    question = payload.get("question")
    if not isinstance(question, str):
        raise ValidationError(["question must be a string"])
    question = question.strip()
    if not Config.QUESTION_MIN_CHARS <= len(question) <= Config.QUESTION_MAX_CHARS:
        raise ValidationError([
            "question must be between {} and {} characters".format(
                Config.QUESTION_MIN_CHARS, Config.QUESTION_MAX_CHARS
            )
        ])

    # Seed the shared corpus from the database before asking about inventory.
    rag_client.ensure_synced(db_client.list_stock)
    outcome = rag_client.ask(question)
    outcome["question"] = question
    return jsonify(outcome)


@api.post("/api/stock/rag-sync")
def rag_sync():
    """Re-index all inventory records into the shared RAG corpus."""
    return jsonify(rag_client.sync_stocks(db_client.list_stock()))


# ----------------------------------------------------------- error handlers
@api.app_errorhandler(ValidationError)
def handle_validation_error(exc):
    """Return business-rule failures in a consistent JSON shape."""
    return jsonify({"error": "validation failed", "details": exc.errors}), 400


@api.app_errorhandler(db_client.NotFound)
def handle_not_found(exc):
    """Map missing database records to HTTP 404."""
    return jsonify({"error": str(exc)}), 404


@api.app_errorhandler(db_client.Conflict)
def handle_conflict(exc):
    """Map duplicate SKU writes to HTTP 409."""
    return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@api.app_errorhandler(db_client.DatabaseError)
def handle_database_error(exc):
    """Prevent database transport failures from becoming unhandled 500 errors."""
    return jsonify({"error": "database microservice unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(ai_agent.AIServiceError)
def handle_ai_error(exc):
    """Report a shared AI-Mode outage to API consumers."""
    return jsonify({"error": "AI-Mode service unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPServiceUnavailable)
def handle_mcp_unavailable(exc):
    return jsonify({"error": "MCP server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPBadResponse)
def handle_mcp_bad_response(exc):
    return jsonify({"error": "MCP server returned an invalid result", "detail": str(exc)}), 502


@api.app_errorhandler(rag_client.RAGServiceUnavailable)
def handle_rag_unavailable(exc):
    return jsonify({"error": "RAG server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(rag_client.RAGBadResponse)
def handle_rag_bad_response(exc):
    return jsonify({"error": "RAG server returned an invalid result", "detail": str(exc)}), 502


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
