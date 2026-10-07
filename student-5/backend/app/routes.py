"""REST API for Reviews and Ratings (Student 5).

Endpoints registered in the Project Group Registration Form:

    GET    /api/reviews              list + filter (?product_sku= ?user_id= ?rating= ?sort=)
    POST   /api/reviews              create
    GET    /api/reviews/<id>         read one
    PUT    /api/reviews/<id>         update
    DELETE /api/reviews/<id>         delete
    POST   /api/reviews/ai           AI pros/cons summary of a product's reviews

Plus supporting endpoints: GET /health, GET /api/products (proxied from
Student 1's catalogue, best-effort, for the "which product" picker in the UI).
"""

from flask import Blueprint, jsonify, request

from . import ai_agent, catalogue_client, db_client, mcp_client, rag_client
from .config import Config
from .validation import ValidationError, clean_review

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
    }
    return jsonify(body), (200 if database_ok else 503)


@api.get("/api/products")
def products():
    """Products available to review, proxied from Student 1's catalogue."""
    return jsonify({"products": catalogue_client.list_products()})


# ---------------------------------------------------------------------- CRUD
@api.get("/api/reviews")
def list_reviews():
    reviews = db_client.list_reviews(
        product_sku=request.args.get("product_sku"),
        user_id=request.args.get("user_id"),
        rating=request.args.get("rating"),
        sort=request.args.get("sort", "newest"),
    )
    return jsonify({"count": len(reviews), "reviews": reviews})


@api.get("/api/reviews/<review_id>")
def get_review(review_id):
    return jsonify(db_client.get_review(review_id))


@api.post("/api/reviews")
def create_review():
    payload = clean_review(request.get_json(silent=True) or {})
    row = db_client.create_review(payload)
    rag_client.index_review(row)  # best-effort: keep the shared RAG corpus in sync
    return jsonify(row), 201


@api.put("/api/reviews/<review_id>")
def update_review(review_id):
    payload = clean_review(request.get_json(silent=True) or {}, partial=True)
    row = db_client.update_review(review_id, payload)
    rag_client.index_review(row)  # re-index: the review text may have changed
    return jsonify(row)


@api.delete("/api/reviews/<review_id>")
def delete_review(review_id):
    db_client.delete_review(review_id)
    rag_client.remove_review(review_id)  # best-effort: drop it from the shared corpus
    return jsonify({"deleted": review_id})


# ------------------------------------------------------------------- AI-mode
@api.post("/api/reviews/ai")
def summarise_reviews():
    """Summarise a product's reviews into a short summary, pros and cons."""
    payload = request.get_json(silent=True) or {}
    product_sku = str(payload.get("product_sku", "")).strip().upper()

    if len(product_sku) < 3:
        raise ValidationError(["product_sku is required (at least 3 characters)"])

    name = catalogue_client.product_name(product_sku)
    outcome = ai_agent.summarise_reviews(product_sku, name)
    return jsonify(outcome), (200 if outcome.get("ok") else 502)


# --------------------------------------------------- Release 1: RAG and MCP
@api.post("/api/reviews/ask")
def ask_about_reviews():
    """Grounded Q&A over one product's reviews (shared RAG server + AI-Mode validation)."""
    payload = request.get_json(silent=True) or {}
    product_sku = str(payload.get("product_sku", "")).strip().upper()
    question = str(payload.get("question", "")).strip()

    if len(product_sku) < 3:
        raise ValidationError(["product_sku is required (at least 3 characters)"])
    if len(question) < 5:
        raise ValidationError(["question is required (at least 5 characters)"])

    result = rag_client.ask(product_sku, question)
    if result.get("status") == "ok":
        result["validation"] = ai_agent.validate_rag_answer(
            query=question, answer=result["answer"], sources=result["sources"],
            claimed_confidence=result["confidence"],
        )
    return jsonify(result), 200


@api.post("/api/reviews/moderate")
def moderate_review():
    """Moderation check for a review before it's published (shared MCP server + AI-Mode validation)."""
    payload = request.get_json(silent=True) or {}
    product_sku = str(payload.get("product_sku", "")).strip().upper()
    review_text = str(payload.get("review_text", ""))
    rating = payload.get("rating")

    if len(product_sku) < 3:
        raise ValidationError(["product_sku is required (at least 3 characters)"])
    if not review_text.strip():
        raise ValidationError(["review_text is required"])

    try:
        stats = db_client.product_stats(product_sku)
    except db_client.DatabaseError:
        stats = {}  # grounding is best-effort: a database blip must not block moderation

    arguments = {
        "review_text": review_text,
        "rating": rating,
        "existing_review_count": stats.get("review_count", 0),
        "average_rating": stats.get("avg_rating"),
    }
    tool_outcome = mcp_client.check_review_quality(**arguments)
    tool_result = tool_outcome.get("result", {})

    validation = ai_agent.validate_mcp_result(
        tool_name="check_review_quality", arguments=arguments, result=tool_result,
    )
    return jsonify({"tool_result": tool_result, "validation": validation}), 200


# ----------------------------------------------------------- error handlers
@api.app_errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"error": "validation failed", "details": exc.errors}), 400


@api.app_errorhandler(db_client.NotFound)
def handle_not_found(exc):
    return jsonify({"error": str(exc)}), 404


@api.app_errorhandler(db_client.DatabaseError)
def handle_database_error(exc):
    return jsonify({"error": "database microservice unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(ai_agent.AIServiceError)
def handle_ai_error(exc):
    return jsonify({"error": "AI-Mode service unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPServiceUnavailable)
def handle_mcp_unavailable(exc):
    return jsonify({"error": "MCP server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(mcp_client.MCPBadResponse)
def handle_mcp_bad_response(exc):
    return jsonify({"error": "MCP server returned an invalid result", "detail": str(exc)}), 502


@api.app_errorhandler(rag_client.RAGServiceError)
def handle_rag_error(exc):
    return jsonify({"error": "RAG server unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
