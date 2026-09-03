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

from . import ai_agent, db_client
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
    return jsonify(db_client.create_stock(payload)), 201


@api.put("/api/stock/<int:stock_id>")
def update_stock(stock_id):
    """Validate only supplied fields and update the matching record."""
    payload = clean_stock(request.get_json(silent=True) or {}, partial=True)
    return jsonify(db_client.update_stock(stock_id, payload))


@api.delete("/api/stock/<int:stock_id>")
def delete_stock(stock_id):
    """Delete a stock record and return its identifier for client updates."""
    db_client.delete_stock(stock_id)
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


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
