"""Student 1 - Product Catalogue - FRONTEND microservice.

Server-rendered HTMX interface. Every partial route
returns an HTML fragment that HTMX swaps into the page, so the browser never
talks to the backend/API microservice directly.

    GET  /                          catalogue page
    GET  /partials/products         product table rows (filtered)
    GET  /partials/form             blank create form
    GET  /partials/form/<id>        edit form for one product
    GET  /partials/sku-preview      SKU the chosen category would generate
    POST /products                  create
    POST /products/<id>             update
    POST /products/<id>/delete      delete
    POST /ai/suggest                AI description + price suggestion
    POST /products/<id>/mcp-check   Release 1: shared MCP listing check
    POST /catalogue/ask             Release 1: grounded RAG answer
    POST /products/<id>/multi-agent                 Release 2: start a listing review
    GET  /products/<id>/multi-agent/history         Release 2: workflow history
    GET  /products/<id>/multi-agent/<wid>           Release 2: workflow stages (polled)
    POST /products/<id>/multi-agent/<wid>/review    Release 2: human decision
    GET  /health                    frontend liveness + downstream health
    GET  /shared/<path>             the team's shared CSS/JS (read-only volume)
"""

import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_from_directory

import api_client
from api_client import ApiError

app = Flask(__name__)

DESCRIPTION_PREVIEW = 110
app.jinja_env.globals["DESCRIPTION_PREVIEW"] = DESCRIPTION_PREVIEW

HOME_URL = os.getenv("HOME_URL", "http://localhost:3000")
STATUSES = ("active", "draft", "archived")

# The catalogue opens on the rows that changed most recently; the value must
# match one of the keys the database microservice knows (db.SORT_COLUMNS).
DEFAULT_SORT = "latest"
SORT_OPTIONS = (
    ("latest", "Recently updated"),
    ("name", "Name (A to Z)"),
    ("price_asc", "Price (low to high)"),
    ("price_desc", "Price (high to low)"),
)

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


@app.template_filter("last_activity")
def last_activity(product):
    """The later of a product's ``updated_at`` / ``created_at`` stamps.

    The Updated column reports recency, so a row created after its last edit
    (or seeded with no edit at all) still shows when it actually last changed.
    Both stamps are ``YYYY-MM-DD[ HH:MM:SS]``, which sorts correctly as text.
    """
    stamps = [str(product.get(key) or "") for key in ("updated_at", "created_at")]
    return max(stamps)


@app.template_filter("short_date")
def short_date(value):
    if not value:
        return "—"
    try:
        stamp = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
    return "{} {} {}".format(stamp.day, stamp.strftime("%b"), stamp.year)


# ------------------------------------------------------------------- helpers
def _filters():
    return {
        "search": request.args.get("search", "").strip(),
        "category": request.args.get("category", "").strip(),
        "status": request.args.get("status", "").strip(),
        "sort": request.args.get("sort", DEFAULT_SORT).strip(),
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
        sort_options=SORT_OPTIONS,
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


@app.post("/products/<int:product_id>/mcp-check")
def mcp_check(product_id):
    """Shared MCP tool check_product_listing, through the backend/API."""
    try:
        outcome = api_client.check_listing(product_id)
    except ApiError as exc:
        return render_template("partials/mcp_result.html", error=exc.message)
    return render_template(
        "partials/mcp_result.html", outcome=outcome, result=outcome.get("result", {})
    )


@app.post("/catalogue/ask")
def ask_catalogue():
    """Grounded answer from the shared RAG server, through the backend/API."""
    question = request.form.get("question", "").strip()
    if len(question) < 5:
        return render_template(
            "partials/rag_result.html",
            error="Ask a question about the catalogue (at least 5 characters).",
        )
    try:
        outcome = api_client.ask_catalogue(question)
    except ApiError as exc:
        return render_template("partials/rag_result.html", error=exc.message)
    return render_template("partials/rag_result.html", outcome=outcome)


# ------------------------------------------------- Release 2: Multi-Agent
# Stages during which the panel keeps polling the workflow for progress.
RUNNING_STAGES = ("queued", "planning", "working", "reviewing", "revising")
app.jinja_env.globals["RUNNING_STAGES"] = RUNNING_STAGES


def _lines(field):
    return [line.strip() for line in request.form.get(field, "").splitlines() if line.strip()]


def _workflow_panel(product_id, workflow=None, error=None, status=200):
    return (
        render_template(
            "partials/multi_agent_result.html",
            product_id=product_id,
            workflow=workflow,
            error=error,
        ),
        status,
    )


@app.post("/products/<int:product_id>/multi-agent")
def start_multi_agent(product_id):
    """Queue a Planner -> Worker -> Reviewer review, then show its first state."""
    try:
        started = api_client.start_multi_agent_review(product_id)
        workflow = api_client.get_multi_agent_workflow(product_id, started["workflow_id"])
    except ApiError as exc:
        return _workflow_panel(product_id, error=exc.message)
    return _workflow_panel(product_id, workflow)


@app.get("/products/<int:product_id>/multi-agent/history")
def multi_agent_history(product_id):
    try:
        history = api_client.list_multi_agent_workflows(product_id)
    except ApiError as exc:
        return render_template(
            "partials/multi_agent_history.html",
            product_id=product_id, workflows=[], error=exc.message, current=None,
        )
    return render_template(
        "partials/multi_agent_history.html",
        product_id=product_id, workflows=history.get("workflows", []), error=None,
        current=request.args.get("current"),
    )


@app.get("/products/<int:product_id>/multi-agent/<workflow_id>")
def multi_agent_status(product_id, workflow_id):
    try:
        workflow = api_client.get_multi_agent_workflow(product_id, workflow_id)
    except ApiError as exc:
        return _workflow_panel(product_id, error=exc.message)
    return _workflow_panel(product_id, workflow)


@app.post("/products/<int:product_id>/multi-agent/<workflow_id>/review")
def review_multi_agent(product_id, workflow_id):
    """Human review: accept, partially accept with corrections, or reject."""
    decision = request.form.get("decision", "").strip()
    payload = {"decision": decision, "feedback": request.form.get("feedback", "").strip()}
    if decision == "partial_accept":
        payload.update(
            {
                "corrected_output": {
                    "recommendation": request.form.get("corrected_recommendation", "").strip(),
                    "rationale": request.form.get("corrected_rationale", "").strip(),
                },
                "accepted_fields": _lines("accepted_fields"),
                "unresolved_issues": _lines("unresolved_issues"),
            }
        )
    elif decision == "reject":
        payload["unresolved_issues"] = _lines("unresolved_issues")

    try:
        workflow = api_client.review_multi_agent_workflow(product_id, workflow_id, payload)
    except ApiError as exc:
        # Re-show the workflow with the error so the administrator can retry.
        try:
            workflow = api_client.get_multi_agent_workflow(product_id, workflow_id)
        except ApiError:
            workflow = None
        return _workflow_panel(product_id, workflow, error=exc.message)
    return _workflow_panel(product_id, workflow)


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
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "3001")), debug=False)
