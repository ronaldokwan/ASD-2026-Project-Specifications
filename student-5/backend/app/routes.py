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

from . import ai_agent, catalogue_client, db_client
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
    return jsonify(db_client.create_review(payload)), 201


@api.put("/api/reviews/<review_id>")
def update_review(review_id):
    payload = clean_review(request.get_json(silent=True) or {}, partial=True)
    return jsonify(db_client.update_review(review_id, payload))


@api.delete("/api/reviews/<review_id>")
def delete_review(review_id):
    db_client.delete_review(review_id)
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


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
