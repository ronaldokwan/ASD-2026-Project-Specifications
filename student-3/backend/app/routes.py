"""REST API for Student 3 Customer Account Management."""

from flask import Blueprint, jsonify, request

from . import ai_agent, db_client
from .config import Config
from .validation import ValidationError, clean_customer

api = Blueprint("api", __name__)


@api.get("/health")
def health():
    try:
        database = db_client.health()
        database_ok = True
    except db_client.DatabaseError as exc:
        database, database_ok = {"error": str(exc)}, False
    return jsonify({
        "service": Config.SERVICE_NAME,
        "student": Config.STUDENT,
        "owner": Config.OWNER,
        "feature": Config.FEATURE,
        "status": "ok" if database_ok else "degraded",
        "database": database,
        "ai_mode": ai_agent.ai_mode_health(),
    }), (200 if database_ok else 503)


@api.get("/api/customers")
def list_customers():
    customers = db_client.list_customers(search=request.args.get("search"))
    return jsonify({"count": len(customers), "customers": customers})


@api.get("/api/customers/<int:customer_id>")
def get_customer(customer_id):
    return jsonify(db_client.get_customer(customer_id))


@api.post("/api/customers")
def create_customer():
    payload = clean_customer(request.get_json(silent=True) or {})
    return jsonify(db_client.create_customer(payload)), 201


@api.put("/api/customers/<int:customer_id>")
def update_customer(customer_id):
    payload = clean_customer(request.get_json(silent=True) or {}, partial=True)
    return jsonify(db_client.update_customer(customer_id, payload))


@api.delete("/api/customers/<int:customer_id>")
def delete_customer(customer_id):
    db_client.delete_customer(customer_id)
    return jsonify({"deleted": customer_id})


@api.post("/api/customers/<int:customer_id>/ai-reward")
def ai_reward(customer_id):
    customer = db_client.get_customer(customer_id)
    return jsonify(ai_agent.suggest_reward(customer))


@api.app_errorhandler(ValidationError)
def handle_validation_error(exc):
    return jsonify({"error": "validation failed", "details": exc.errors}), 400


@api.app_errorhandler(db_client.NotFound)
def handle_not_found(exc):
    return jsonify({"error": str(exc)}), 404


@api.app_errorhandler(db_client.Conflict)
def handle_conflict(exc):
    return jsonify({"error": "email already exists", "detail": str(exc)}), 409


@api.app_errorhandler(db_client.DatabaseError)
def handle_database_error(exc):
    return jsonify({"error": "database microservice unavailable", "detail": str(exc)}), 503


@api.app_errorhandler(404)
def handle_unknown_route(_):
    return jsonify({"error": "endpoint not found"}), 404


@api.app_errorhandler(405)
def handle_bad_method(_):
    return jsonify({"error": "method not allowed for this endpoint"}), 405
