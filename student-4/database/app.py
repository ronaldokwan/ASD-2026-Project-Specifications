"""Student 4 - Inventory and Stock - DATABASE microservice.

Owns the SQLite database and exposes it as a small internal data API. Only the
Student 4 backend/API microservice is expected to call it.

    GET    /health
    GET    /stock?category=&stock_level=&sku=&search=&sort=
    GET    /stock/<id>
    POST   /stock
    PUT    /stock/<id>
    DELETE /stock/<id>
    GET    /stock/low                        low-stock items (qty <= threshold)
    POST   /admin/reseed                     reset to the seed records
"""

import os

from flask import Flask, jsonify, request

import db

app = Flask(__name__)

SEEDED_COUNT = db.init_db()
# Initialise once at service startup so a new database has demonstration records.
app.logger.info("Inventory and Stock database ready at %s (%s rows)", db.DB_PATH, SEEDED_COUNT)


@app.get("/health")
def health():
    """Confirm that the SQLite store is accessible and report its record count."""
    try:
        rows = db.count_stock()
    except Exception as exc:  # pragma: no cover - only on a corrupt volume
        return jsonify({"service": "student-4-database", "status": "error", "error": str(exc)}), 503
    return jsonify({
        "service": "student-4-database",
        "student": 4,
        "owner": "Jonathan Czesler",
        "feature": "Inventory and Stock",
        "status": "ok",
        "db_path": db.DB_PATH,
        "stock_items": rows,
    })


@app.get("/stock")
def list_stock():
    """Expose filtered inventory reads to the backend microservice."""
    stock = db.list_stock(
        category=request.args.get("category"),
        stock_level=request.args.get("stock_level"),
        sku=request.args.get("sku"),
        search=request.args.get("search"),
        sort=request.args.get("sort", "name"),
        limit=request.args.get("limit", 200),
    )
    return jsonify({"count": len(stock), "stock": stock})


@app.get("/stock/low")
def list_low_stock():
    """Return items below restock threshold."""
    low = db.list_low_stock(limit=request.args.get("limit", 200))
    return jsonify({"count": len(low), "low_stock": low})


@app.get("/stock/<int:stock_id>")
def get_stock(stock_id):
    """Return a stock record by id or an API-friendly not-found response."""
    try:
        return jsonify(db.get_stock(stock_id))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/stock")
def create_stock():
    """Persist a stock record received from the backend API."""
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.create_stock(payload)), 201
    except db.Conflict as exc:
        return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@app.put("/stock/<int:stock_id>")
def update_stock(stock_id):
    """Update an existing stock record with the supplied JSON fields."""
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.update_stock(stock_id, payload))
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except db.Conflict as exc:
        return jsonify({"error": "sku already exists", "detail": str(exc)}), 409


@app.delete("/stock/<int:stock_id>")
def delete_stock(stock_id):
    """Delete a record after converting an absent id into a 404 response."""
    try:
        db.delete_stock(stock_id)
    except db.NotFound as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"deleted": stock_id})


@app.post("/admin/reseed")
def reseed():
    """Restore the table to its seed records (demo / testing convenience)."""
    count = db.init_db(force_reseed=True)
    return jsonify({"reseeded": True, "stock_items": count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "9004")), debug=True)
