"""REST API for the Product Catalogue (Student 1).

Endpoints registered in the Project Group Registration Form:

    GET    /health
    GET    /products?category=&status=&sku=&search=&sort=
    GET    /products/<id>
    POST   /products
    PUT    /products/<id>
    DELETE /products/<id>
    GET    /categories
    GET    /next-sku?category=            preview the next generated SKU
    GET    /stats/category/<category>     facts used to ground the AI
    POST   /admin/reseed                  reset to the 12 seed records

Release 1 (shared MCP and RAG servers, both outside Docker Compose):

    POST   /api/products/<id>/mcp-check   MCP tool check_product_listing
    POST   /api/catalogue/ask             grounded RAG answer with citations
    POST   /api/catalogue/rag-sync        re-index every product into the RAG corpus
"""

from flask import Blueprint, jsonify, request

from . import ai_agent, db_client, mcp_client, rag_client
from .config import Config
from .validation import ValidationError, canonical_category, clean_product

api = Blueprint("api", __name__)


# --------------------------------------------------------------------- meta
@api.get("/health")
def health():
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


@api.get("/api/categories")
def categories():
    """Categories in use (with counts), plus the closed set writes accept.

    ``categories`` is unchanged and still data-driven, so existing consumers
    keep working. ``valid_categories`` is additive: a category with no products
    yet appears there but not in ``categories``, which is what the create form
    needs in order to offer it at all.
    """
    return jsonify(
        {
            "categories": db_client.list_categories(),
            "valid_categories": list(Config.VALID_CATEGORIES),
        }
    )


# ---------------------------------------------------------------------- CRUD
@api.get("/api/products")
def list_products():
    products = db_client.list_products(
        sku=request.args.get("sku"),
        category=request.args.get("category"),
        status=request.args.get("status"),
        search=request.args.get("search"),
        sort=request.args.get("sort", Config.DEFAULT_SORT),
    )
    return jsonify({"count": len(products), "products": products})


@api.get("/api/products/next-sku")
def next_sku():
    """The SKU a create would assign for ?category=, for form previews.

    Declared before the /<int:product_id> route for readability; the int
    converter would not match "next-sku" in any case.
    """
    category = canonical_category(request.args.get("category", ""))
    if category is None:
        raise ValidationError(
            ["category must be one of {}".format(", ".join(Config.VALID_CATEGORIES))]
        )
    return jsonify({"category": category, "sku": db_client.next_sku(category)})


@api.get("/api/products/<int:product_id>")
def get_product(product_id):
    return jsonify(db_client.get_product(product_id))


@api.post("/api/products")
def create_product():
    payload = clean_product(request.get_json(silent=True) or {})
    product = db_client.create_product(payload)
    rag_client.sync_product(product)
    return jsonify(product), 201


@api.put("/api/products/<int:product_id>")
def update_product(product_id):
    payload = clean_product(request.get_json(silent=True) or {}, partial=True)
    product = db_client.update_product(product_id, payload)
    rag_client.sync_product(product)
    return jsonify(product)


@api.delete("/api/products/<int:product_id>")
def delete_product(product_id):
    db_client.delete_product(product_id)
    rag_client.remove_product(product_id)
    return jsonify({"deleted": product_id})


# ------------------------------------------------------------------- AI-mode
@api.post("/api/products/ai")
def generate_product_copy():
    """Generate a description and price suggestion for a draft product."""
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    keywords = str(payload.get("keywords", "")).strip()

    errors = []
    if len(name) < 2:
        errors.append("name is required (at least 2 characters)")
    category = canonical_category(category) if category else None
    if category is None:
        errors.append(
            "category must be one of {}".format(", ".join(Config.VALID_CATEGORIES))
        )
    if errors:
        raise ValidationError(errors)

    outcome = ai_agent.suggest_product_copy(name, category, keywords)
    return jsonify(outcome), (200 if outcome.get("ok") else 502)


# ------------------------------------------------------------ Release 1: MCP
@api.post("/api/products/<int:product_id>/mcp-check")
def mcp_listing_check(product_id):
    """Run the shared MCP tool check_product_listing for one product."""
    product = db_client.get_product(product_id)
    return jsonify(mcp_client.check_listing(product))


@api.post("/api/catalogue/ask")
def ask_catalogue():
    """Grounded answer about the catalogue from the shared RAG server."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])
    question = payload.get("question")
    if not isinstance(question, str):
        raise ValidationError(["question must be a string"])
    question = question.strip()
    if not Config.QUESTION_MIN_CHARS <= len(question) <= Config.QUESTION_MAX_CHARS:
        raise ValidationError(
            [
                "question must be between {} and {} characters".format(
                    Config.QUESTION_MIN_CHARS, Config.QUESTION_MAX_CHARS
                )
            ]
        )

    rag_client.ensure_synced(db_client.list_products)
    outcome = rag_client.ask(question)
    outcome["question"] = question
    return jsonify(outcome)


@api.post("/api/catalogue/rag-sync")
def rag_sync():
    """Re-index every catalogue product into the shared RAG corpus."""
    return jsonify(rag_client.sync_products(db_client.list_products()))


# ----------------------------------------------------------- error handlers
@api.app_errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"error": "validation failed", "details": exc.errors}), 400


@api.app_errorhandler(db_client.NotFound)
def handle_not_found(exc):
    return jsonify({"error": str(exc)}), 404


@api.app_errorhandler(db_client.Conflict)
def handle_conflict(exc):
    return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@api.app_errorhandler(db_client.DatabaseError)
def handle_database_error(exc):
    return (
        jsonify({"error": "database microservice unavailable", "detail": str(exc)}),
        503,
    )


@api.app_errorhandler(ai_agent.AIServiceError)
def handle_ai_error(exc):
    return jsonify({"error": "AI-Mode service unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPServiceUnavailable)
def handle_mcp_unavailable(exc):
    return jsonify({"error": "MCP server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPBadResponse)
def handle_mcp_bad_response(exc):
    return (
        jsonify({"error": "MCP server returned an invalid result", "detail": str(exc)}),
        502,
    )


@api.app_errorhandler(rag_client.RAGServiceUnavailable)
def handle_rag_unavailable(exc):
    return jsonify({"error": "RAG server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(rag_client.RAGBadResponse)
def handle_rag_bad_response(exc):
    return (
        jsonify({"error": "RAG server returned an invalid result", "detail": str(exc)}),
        502,
    )


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
