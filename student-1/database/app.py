"""Student 1 - Product Catalogue - DATABASE microservice.

Owns the SQLite database and exposes it as a small internal data API. Only the
Student 1 backend/API microservice is expected to call it.

    GET    /health
    GET    /products?category=&status=&sku=&search=&sort=
    GET    /products/<id>
    POST   /products
    PUT    /products/<id>
    DELETE /products/<id>
    GET    /categories
    GET    /stats/category/<category>     facts used to ground the AI
    POST   /admin/reseed                  reset to the 12 seed records
"""

import os

from flask import Flask, jsonify, request

import db

app = Flask(__name__)

SEEDED_COUNT = db.init_db()
app.logger.info("Product Catalogue database ready at %s (%s rows)", db.DB_PATH, SEEDED_COUNT)


@app.get("/health")
def health():
    try:
        rows = db.count_products()
    except Exception as exc:  # pragma: no cover - only on a corrupt volume
        return jsonify({"service": "student-1-db", "status": "error", "error": str(exc)}), 503
    return jsonify({
        "service": "student-1-db",
        "student": 1,
        "owner": "Ronaldo Kwan",
        "feature": "Product Catalogue",
        "status": "ok",
        "db_path": db.DB_PATH,
        "products": rows,
    })


@app.get("/products")
def list_products():
    products = db.list_products(
        category=request.args.get("category"),
        status=request.args.get("status"),
        sku=request.args.get("sku"),
        search=request.args.get("search"),
        sort=request.args.get("sort", "name"),
        limit=request.args.get("limit", 200),
    )
    return jsonify({"count": len(products), "products": products})


@app.get("/products/<int:product_id>")
def get_product(product_id):
    try:
        return jsonify(db.get_product(product_id))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/products")
def create_product():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.create_product(payload)), 201
    except db.Conflict as exc:
        return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@app.put("/products/<int:product_id>")
def update_product(product_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.update_product(product_id, payload))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except db.Conflict as exc:
        return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@app.delete("/products/<int:product_id>")
def delete_product(product_id):
    try:
        db.delete_product(product_id)
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"deleted": product_id})


@app.get("/categories")
def categories():
    return jsonify({"categories": db.list_categories()})


@app.get("/stats/category/<path:category>")
def stats(category):
    return jsonify(db.category_stats(category))


@app.post("/admin/reseed")
def reseed():
    """Restore the table to its 12 seed records (demo / testing convenience)."""
    count = db.init_db(force_reseed=True)
    return jsonify({"reseeded": True, "products": count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "9001")), debug=True)
