"""Student 4 - Inventory and Stock - FRONTEND microservice.

Server-rendered HTMX interface. Every partial route
returns an HTML fragment that HTMX swaps into the page, so the browser never
talks to the backend/API microservice directly.

    GET  /                          inventory page
    GET  /partials/products         stock table rows (filtered)
    GET  /partials/form             blank create form
    GET  /partials/form/<id>        edit form for one stock item
    POST /stock                     create
    POST /stock/<id>                update
    POST /stock/<id>/delete         delete
    POST /ai/recommend              AI restock recommendation
    GET  /health                    frontend liveness + downstream health
    GET  /shared/<path>             the team's shared CSS/JS (read-only volume)
"""

import os

from flask import Flask, jsonify, render_template, request, send_from_directory

import api_client
from api_client import ApiError

app = Flask(__name__)

HOME_URL = os.getenv("HOME_URL", "http://localhost:3000")
STOCK_LEVELS = ("good", "low")

# The team's shared theme is mounted read-only by docker-compose; fall back to
# the repository copy when the frontend is run directly on a laptop.
SHARED_DIR = os.getenv("SHARED_DIR", "/app/shared")
if not os.path.isdir(SHARED_DIR):
    SHARED_DIR = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared")
    )


@app.get("/shared/<path:filename>")
def shared_asset(filename):
    """Serve the shared read-only assets when the app runs outside Docker."""
    return send_from_directory(SHARED_DIR, filename)


# ------------------------------------------------------------------- helpers
def _filters():
    """Read and normalise the query parameters accepted by the stock table."""
    return {
        "search": request.args.get("search", "").strip(),
        "category": request.args.get("category", "").strip(),
        "stock_level": request.args.get("stock_level", "").strip(),
        "sort": request.args.get("sort", "name").strip(),
    }


def _categories():
    """Build an ordered, de-duplicated category list for form and filter controls."""
    try:
        categories = []
        for row in api_client.list_stock():
            category = str(row.get("category", "")).strip()
            if category and category not in categories:
                categories.append(category)
        return categories
    except ApiError:
        return []


def _form_payload(form):
    """Convert browser form data into the stock API's JSON field names."""
    return {
        "sku": form.get("sku", "").strip(),
        "name": form.get("name", "").strip(),
        "category": form.get("category", "").strip(),
        "location": form.get("location", "").strip(),
        "quantity": form.get("quantity", "").strip(),
        "restock_threshold": form.get("restock_threshold", "").strip(),
        "stock_level": form.get("stock_level", "good").strip(),
    }


def _alert(message, level="ok"):
    """Render a reusable HTMX feedback banner."""
    return render_template("partials/alert.html", message=message, level=level)


def _table(oob=False):
    """Render the stock table with the current filters applied."""
    filters = _filters()
    stock = api_client.list_stock(**filters)
    return render_template(
        "partials/product_table.html", stock=stock, products=stock, filters=filters, oob=oob
    )


# --------------------------------------------------------------------- pages
@app.get("/")
def index():
    """Render the full inventory page, including any initial backend error."""
    filters = _filters()
    error = None
    stock = []
    try:
        stock = api_client.list_stock(**filters)
    except ApiError as exc:
        error = exc.message

    return render_template(
        "index.html",
        stock=stock,
        products=stock,
        filters=filters,
        categories=_categories(),
        statuses=STOCK_LEVELS,
        error=error,
        home_url=HOME_URL,
    )


@app.get("/partials/products")
def partial_products():
    """Return only the filtered table fragment for an HTMX swap."""
    try:
        return _table()
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status


@app.get("/partials/form")
def partial_new_form():
    """Return an empty stock form when editing is cancelled."""
    return render_template(
        "partials/product_form.html",
        product=None,
        categories=_categories(),
        statuses=STOCK_LEVELS,
    )


@app.get("/partials/form/<int:stock_id>")
def partial_edit_form(stock_id):
    """Fetch an item and render its values in the reusable stock form."""
    try:
        item = api_client.get_stock(stock_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return render_template(
        "partials/product_form.html",
        product=item,
        categories=_categories(),
        statuses=STOCK_LEVELS,
    )


# ---------------------------------------------------------------------- CRUD
@app.post("/stock")
def create_stock():
    """Create an item, then refresh the table and form with HTMX OOB swaps."""
    payload = _form_payload(request.form)
    try:
        item = api_client.create_stock(payload)
    except ApiError as exc:
        return _validation_response(exc, payload)

    return (
        _alert('Created "{}" ({}).'.format(item["name"], item["sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/stock/<int:stock_id>")
def update_stock(stock_id):
    """Save an edited item, then refresh the table and reset the form."""
    payload = _form_payload(request.form)
    try:
        item = api_client.update_stock(stock_id, payload)
    except ApiError as exc:
        return _validation_response(exc, payload, stock_id)

    return (
        _alert('Updated "{}" ({}).'.format(item["name"], item["sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/products")
def create_product():
    return create_stock()


@app.post("/products/<int:product_id>")
def update_product(product_id):
    return update_stock(product_id)


@app.post("/stock/<int:stock_id>/delete")
def delete_stock(stock_id):
    """Delete an item and return the updated stock table fragment."""
    try:
        api_client.delete_stock(stock_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return _alert("Stock item #{} deleted.".format(stock_id)) + _table(oob=True)


@app.post("/products/<int:product_id>/delete")
def delete_product(product_id):
    return delete_stock(product_id)


def _validation_response(exc, payload, stock_id=None):
    """Re-render the submitted form alongside validation details from the API."""
    """Re-render the form with the API's validation messages attached."""
    item = dict(payload)
    if stock_id:
        item["id"] = stock_id
    form = render_template(
        "partials/product_form.html",
        product=item,
        categories=_categories(),
        statuses=STOCK_LEVELS,
        errors=exc.details or [exc.message],
        oob=True,
    )
    return _alert(exc.message, "error") + form, 200


def _blank_form_oob():
    """Render a blank form marked for an out-of-band HTMX replacement."""
    return render_template(
        "partials/product_form.html",
        product=None,
        categories=_categories(),
        statuses=STOCK_LEVELS,
        oob=True,
    )


# ------------------------------------------------------------------- AI-Mode
@app.post("/ai/recommend")
def ai_recommend():
    """Run the Plan -> Act -> Observe -> Adapt loop for low-stock restocking."""
    category = request.form.get("category", "").strip()

    if len(category) < 2:
        return render_template(
            "partials/ai_result.html",
            error="Enter a category first, then ask the AI.",
        )

    try:
        outcome = api_client.generate_recommendation(category)
    except ApiError as exc:
        return render_template("partials/ai_result.html", error=exc.message)

    return render_template(
        "partials/ai_result.html",
        outcome=outcome,
        result=outcome.get("result", {}),
    )


@app.post("/ai/suggest")
def ai_suggest():
    return ai_recommend()


# -------------------------------------------------------------------- health
@app.get("/health")
def health():
    """Report frontend health and include the backend's health status."""
    downstream = api_client.backend_health()
    healthy = downstream.get("status") == "ok"
    return jsonify(
        {
            "service": "student-4-frontend",
            "student": 4,
            "owner": "Jonathan Czesler",
            "feature": "Inventory and Stock",
            "status": "ok" if healthy else "degraded",
            "backend": downstream,
        }
    ), (200 if healthy else 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "3004")), debug=True)
