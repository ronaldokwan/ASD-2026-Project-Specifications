"""Student 5 - Reviews and Ratings - FRONTEND microservice.

Server-rendered HTMX interface. Every partial route returns an HTML fragment
that HTMX swaps into the page, so the browser never talks to the backend/API
microservice directly.

    GET  /                          reviews page
    GET  /partials/reviews          review list (filtered)
    GET  /partials/form             blank create form
    GET  /partials/form/<id>        edit form for one review
    POST /reviews                   create
    POST /reviews/<id>              update
    POST /reviews/<id>/delete       delete
    POST /ai/summary                AI pros/cons summary of a product's reviews
    GET  /health                    frontend liveness + downstream health
    GET  /shared/<path>             the team's shared CSS/JS (read-only volume)
"""

import os

from flask import Flask, jsonify, render_template, request, send_from_directory

import api_client
from api_client import ApiError

app = Flask(__name__)

HOME_URL = os.getenv("HOME_URL", "http://localhost:3000")

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
        "product_sku": request.args.get("product_sku", "").strip().upper(),
        "rating": request.args.get("rating", "").strip(),
        "sort": request.args.get("sort", "newest").strip(),
    }


def _products():
    try:
        return api_client.list_products()
    except ApiError:
        return []


def _form_payload(form):
    return {
        "product_sku": form.get("product_sku", "").strip().upper(),
        "user_id": form.get("user_id", "").strip(),
        "rating": form.get("rating", "").strip(),
        "review": form.get("review", "").strip(),
    }


def _alert(message, level="ok"):
    return render_template("partials/alert.html", message=message, level=level)


def _table(oob=False):
    """Render the review list with the current filters applied.

    ``oob=True`` marks the fragment as an HTMX out-of-band swap, used when the
    primary swap target of the response is the alert area instead.
    """
    filters = _filters()
    reviews = api_client.list_reviews(**filters)
    products_by_sku = {p["sku"]: p["name"] for p in _products() if p.get("sku")}
    for review in reviews:
        review["product_name"] = products_by_sku.get(review["product_sku"], review["product_sku"])
    return render_template(
        "partials/review_table.html", reviews=reviews, filters=filters, oob=oob
    )


# --------------------------------------------------------------------- pages
@app.get("/")
def index():
    filters = _filters()
    error = None
    reviews = []
    products = _products()
    try:
        reviews = api_client.list_reviews(**filters)
        products_by_sku = {p["sku"]: p["name"] for p in products}
        for review in reviews:
            review["product_name"] = products_by_sku.get(review["product_sku"], review["product_sku"])
    except ApiError as exc:
        error = exc.message

    return render_template(
        "index.html",
        reviews=reviews,
        filters=filters,
        products=products,
        error=error,
        home_url=HOME_URL,
    )


@app.get("/partials/reviews")
def partial_reviews():
    try:
        return _table()
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status


@app.get("/partials/form")
def partial_new_form():
    return render_template("partials/review_form.html", review=None, products=_products())


@app.get("/partials/form/<review_id>")
def partial_edit_form(review_id):
    try:
        review = api_client.get_review(review_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return render_template("partials/review_form.html", review=review, products=_products())


# ---------------------------------------------------------------------- CRUD
@app.post("/reviews")
def create_review():
    payload = _form_payload(request.form)
    try:
        review = api_client.create_review(payload)
    except ApiError as exc:
        return _validation_response(exc, payload)

    return (
        _alert("Review for {} saved.".format(review["product_sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/reviews/<review_id>")
def update_review(review_id):
    payload = _form_payload(request.form)
    try:
        review = api_client.update_review(review_id, payload)
    except ApiError as exc:
        return _validation_response(exc, payload, review_id)

    return (
        _alert("Review for {} updated.".format(review["product_sku"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/reviews/<review_id>/delete")
def delete_review(review_id):
    try:
        api_client.delete_review(review_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return _alert("Review deleted.") + _table(oob=True)


def _validation_response(exc, payload, review_id=None):
    """Re-render the form with the API's validation messages attached."""
    review = dict(payload)
    if review_id:
        review["review_id"] = review_id
    form = render_template(
        "partials/review_form.html",
        review=review,
        products=_products(),
        errors=exc.details or [exc.message],
        oob=True,
    )
    return _alert(exc.message, "error") + form, 200


def _blank_form_oob():
    return render_template("partials/review_form.html", review=None, products=_products(), oob=True)


# ------------------------------------------------------------------- AI-Mode
@app.post("/ai/summary")
def ai_summary():
    """Run the Plan -> Act -> Observe -> Adapt loop for the selected product."""
    product_sku = request.form.get("product_sku", "").strip().upper()

    if len(product_sku) < 3:
        return render_template(
            "partials/ai_result.html",
            error="Choose a product first, then ask the AI to summarise its reviews.",
        )

    try:
        outcome = api_client.generate_summary(product_sku)
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
            "service": "student-5-frontend",
            "student": 5,
            "owner": "Alexander McGuinn",
            "feature": "Reviews and Ratings",
            "status": "ok" if healthy else "degraded",
            "backend": downstream,
        }
    ), (200 if healthy else 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "3005")), debug=True)
