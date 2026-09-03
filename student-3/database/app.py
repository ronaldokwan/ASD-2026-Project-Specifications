"""Student 3 Customer Account Management database HTTP API."""

import os

from flask import Flask, jsonify, request

import db

app = Flask(__name__)
SEEDED_COUNT = db.init_db()
app.logger.info("Customer database ready at %s (%s rows)", db.DB_PATH, SEEDED_COUNT)


@app.get("/health")
def health():
    try:
        count = db.count_customers()
    except Exception as exc:  # pragma: no cover - corrupt or inaccessible volume
        return jsonify({"service": "student-3-db", "status": "error", "error": str(exc)}), 503
    return jsonify({
        "service": "student-3-db",
        "student": 3,
        "feature": "Customer Account Management",
        "status": "ok",
        "db_path": db.DB_PATH,
        "customers": count,
    })


@app.get("/customers")
def list_customers():
    customers = db.list_customers(
        search=request.args.get("search"),
        limit=request.args.get("limit", 200),
    )
    return jsonify({"count": len(customers), "customers": customers})


@app.get("/customers/<int:customer_id>")
def get_customer(customer_id):
    try:
        return jsonify(db.get_customer(customer_id))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/customers")
def create_customer():
    try:
        return jsonify(db.create_customer(request.get_json(silent=True) or {})), 201
    except db.Conflict as exc:
        return jsonify({"error": "email already exists", "detail": str(exc)}), 409


@app.put("/customers/<int:customer_id>")
def update_customer(customer_id):
    try:
        return jsonify(db.update_customer(customer_id, request.get_json(silent=True) or {}))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except db.Conflict as exc:
        return jsonify({"error": "email already exists", "detail": str(exc)}), 409


@app.delete("/customers/<int:customer_id>")
def delete_customer(customer_id):
    try:
        db.delete_customer(customer_id)
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"deleted": customer_id})


@app.post("/admin/reseed")
def reseed():
    count = db.init_db(force_reseed=True)
    return jsonify({"reseeded": True, "customers": count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "9003")), debug=True)
