"""Student 1 - Product Catalogue - FRONTEND microservice.

Server-rendered HTMX interface. Every partial route
returns an HTML fragment that HTMX swaps into the page, so the browser never
talks to the backend/API microservice directly.

    GET  /                          catalogue page
    GET  /partials/products         product table rows (filtered)
    GET  /partials/form             blank create form
    GET  /partials/form/<id>        edit form for one product
    POST /products                  create
    POST /products/<id>             update
    POST /products/<id>/delete      delete
    POST /ai/suggest                AI description + price suggestion
    GET  /health                    frontend liveness + downstream health
    GET  /shared/<path>             the team's shared CSS/JS (read-only volume)
"""

import os

from flask import Flask, jsonify, render_template, request, send_from_directory

import api_client
from api_client import ApiError

app = Flask(__name__)

HOME_URL = os.getenv("HOME_URL", "http://localhost:3000")
STATUSES = ("active", "draft", "archived")

# The team's shared theme is mounted read-only by docker-compose; fall back to
# the repository copy when the frontend is run directly on a laptop.
SHARED_DIR = os.getenv("SHARED_DIR", "/app/shared")
if not os.path.isdir(SHARED_DIR):
    SHARED_DIR = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared")
    )


@app.get("/shared/<path:filename>")
def shared_asset(filename):
    return send_from_directory(SHARED_DIR, filename)


# ------------------------------------------------------------------- helpers
def _filters():
    return {
        "search": request.args.get("search", "").strip(),
        "category": request.args.get("category", "").strip(),
        "status": request.args.get("status", "").strip(),
        "sort": request.args.get("sort", "name").strip(),
    }


def _categories():
    try:
        categories = api_client.valid_categories()
        if categories:
            return categories
        return [row["category"] for row in api_client.list_categories()]
    except ApiError:
        return []


def _form_payload(form):
    return {
        "sku": form.get("sku", "").strip(),
        "name": form.get("name", "").strip(),
        "category": form.get("category", "").strip(),
        "price": form.get("price", "").strip(),
        "description": form.get("description", "").strip(),
        "status": form.get("status", "active").strip(),
    }


def _alert(message, level="ok"):
    return render_template("partials/alert.html", message=message, level=level)


def _table(oob=False):
    """Render the products table with the current filters applied.

    ``oob=True`` marks the fragment as an HTMX out-of-band swap, used when the
    primary swap target of the response is the alert area instead.
    """
    filters = _filters()
    products = api_client.list_products(**filters)
    return render_template(
        "partials/product_table.html", products=products, filters=filters, oob=oob
    )


# --------------------------------------------------------------------- pages
@app.get("/")
def index():
    filters = _filters()
    error = None
    products = []
    try:
        products = api_client.list_products(**filters)
    except ApiError as exc:
        error = exc.message

    return render_template(
        "index.html",
        products=products,
        filters=filters,
        categories=_categories(),
        statuses=STATUSES,
        error=error,
        home_url=HOME_URL,
    )


@app.get("/partials/products")
def partial_products():
    try:
        return _table()
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status


def _sku_preview(category):
    if not category:
        return ""
    try:
        return api_client.next_sku(category) or ""
    except ApiError:
        return ""


@app.get("/partials/sku-preview")
def partial_sku_preview():
    return render_template(
        "partials/sku_field.html",
        product=None,
        sku_value=_sku_preview(request.args.get("category", "").strip()),
    )


@app.get("/partials/form")
def partial_new_form():
    return render_template(
        "partials/product_form.html",
        product=None,
        categories=_categories(),
        statuses=STATUSES,
        sku_value="",
    )


@app.get("/partials/form/<int:product_id>")
def partial_edit_form(product_id):
    try:
        product = api_client.get_product(product_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return render_template(
        "partials/product_form.html",
        product=product,
        categories=_categories(),
        statuses=STATUSES,
        sku_value=product.get("sku", ""),
    )


# ---------------------------------------------------------------------- CRUD
@app.post("/products")
def create_product():
    payload = _form_payload(request.form)
    try:
        product = api_client.create_product(payload)
    except ApiError as exc:
        return _validation_response(exc, payload)

    return (
        _alert('Created "{}" ({}).'.format(product["name"], product["sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/products/<int:product_id>")
def update_product(product_id):
    payload = _form_payload(request.form)
    try:
        product = api_client.update_product(product_id, payload)
    except ApiError as exc:
        return _validation_response(exc, payload, product_id)

    return (
        _alert('Updated "{}" ({}).'.format(product["name"], product["sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/products/<int:product_id>/delete")
def delete_product(product_id):
    try:
        api_client.delete_product(product_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return _alert("Product #{} deleted.".format(product_id)) + _table(oob=True)


def _validation_response(exc, payload, product_id=None):
    """Re-render the form with the API's validation messages attached."""
    product = dict(payload)
    if product_id:
        product["id"] = product_id

    sku_value = payload.get("sku") or (
        product.get("sku", "")
        if product_id
        else _sku_preview(payload.get("category", ""))
    )
    form = render_template(
        "partials/product_form.html",
        product=product,
        categories=_categories(),
        statuses=STATUSES,
        errors=exc.details or [exc.message],
        oob=True,
        sku_value=sku_value,
    )
    return _alert(exc.message, "error") + form, 200


def _blank_form_oob():
    return render_template(
        "partials/product_form.html",
        product=None,
        categories=_categories(),
        statuses=STATUSES,
        oob=True,
        sku_value="",
    )


# ------------------------------------------------------------------- AI-Mode
@app.post("/ai/suggest")
def ai_suggest():
    """Run the Plan -> Act -> Observe -> Adapt loop for the product in the form."""
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    keywords = request.form.get("keywords", "").strip()

    if len(name) < 2 or len(category) < 2:
        return render_template(
            "partials/ai_result.html",
            error="Enter a product name and a category first, then ask the AI.",
        )

    try:
        outcome = api_client.generate_copy(name, category, keywords)
    except ApiError as exc:
        return render_template("partials/ai_result.html", error=exc.message)

    return render_template(
        "partials/ai_result.html", outcome=outcome, result=outcome.get("result", {})
    )


# -------------------------------------------------------------------- health
@app.get("/health")
def health():
    downstream = api_client.backend_health()
    healthy = downstream.get("status") == "ok"
    return jsonify(
        {
            "service": "student-1-frontend",
            "student": 1,
            "owner": "Ronaldo Kwan",
            "feature": "Product Catalogue",
            "status": "ok" if healthy else "degraded",
            "backend": downstream,
        }
    ), (200 if healthy else 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "3001")), debug=True)
