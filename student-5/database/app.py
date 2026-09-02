"""Student 5 - Reviews and Ratings - DATABASE microservice.

Owns the SQLite database and exposes it as a small internal data API. Only the
Student 5 backend/API microservice is expected to call it.

    GET    /health
    GET    /reviews?product_sku=&user_id=&rating=&sort=
    GET    /reviews/<id>
    POST   /reviews
    PUT    /reviews/<id>
    DELETE /reviews/<id>
    GET    /stats/product/<sku>            facts used to ground the AI
    POST   /admin/reseed                   reset to the 12 seed records
"""

import os

from flask import Flask, jsonify, request

import db

app = Flask(__name__)

SEEDED_COUNT = db.init_db()
app.logger.info("Reviews and Ratings database ready at %s (%s rows)", db.DB_PATH, SEEDED_COUNT)


@app.get("/health")
def health():
    try:
        rows = db.count_reviews()
    except Exception as exc:  # pragma: no cover - only on a corrupt volume
        return jsonify({"service": "student-5-db", "status": "error", "error": str(exc)}), 503
    return jsonify({
        "service": "student-5-db",
        "student": 5,
        "owner": "Alexander McGuinn",
        "feature": "Reviews and Ratings",
        "status": "ok",
        "db_path": db.DB_PATH,
        "reviews": rows,
    })


@app.get("/reviews")
def list_reviews():
    reviews = db.list_reviews(
        product_sku=request.args.get("product_sku"),
        user_id=request.args.get("user_id"),
        rating=request.args.get("rating"),
        sort=request.args.get("sort", "newest"),
        limit=request.args.get("limit", 200),
    )
    return jsonify({"count": len(reviews), "reviews": reviews})


@app.get("/reviews/<review_id>")
def get_review(review_id):
    try:
        return jsonify(db.get_review(review_id))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/reviews")
def create_review():
    payload = request.get_json(silent=True) or {}
    return jsonify(db.create_review(payload)), 201


@app.put("/reviews/<review_id>")
def update_review(review_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.update_review(review_id, payload))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404


@app.delete("/reviews/<review_id>")
def delete_review(review_id):
    try:
        db.delete_review(review_id)
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"deleted": review_id})


@app.get("/stats/product/<path:product_sku>")
def stats(product_sku):
    return jsonify(db.product_stats(product_sku))


@app.post("/admin/reseed")
def reseed():
    """Restore the table to its 12 seed records (demo / testing convenience)."""
    count = db.init_db(force_reseed=True)
    return jsonify({"reseeded": True, "reviews": count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "9005")), debug=True)
