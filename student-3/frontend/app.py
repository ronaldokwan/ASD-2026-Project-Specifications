"""Flask and HTMX frontend for Student 3 Customer Account Management."""

import os

from flask import Flask, jsonify, render_template, request, send_from_directory

import api_client
from api_client import ApiError

app = Flask(__name__)
HOME_URL = os.getenv("HOME_URL", "http://localhost:3000")
LOYALTY_TIERS = ("Bronze", "Silver", "Gold")

SHARED_DIR = os.getenv("SHARED_DIR", "/app/shared")
if not os.path.isdir(SHARED_DIR):
    SHARED_DIR = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared")
    )


@app.get("/shared/<path:filename>")
def shared_asset(filename):
    return send_from_directory(SHARED_DIR, filename)


def _search():
    return request.args.get("search", "").strip()


def _form_payload(form):
    return {
        "name": form.get("name", "").strip(),
        "email": form.get("email", "").strip(),
        "phone": form.get("phone", "").strip(),
        "address": form.get("address", "").strip(),
        "loyalty_tier": form.get("loyalty_tier", "Bronze").strip(),
        "joined_at": form.get("joined_at", "").strip(),
    }


def _alert(message, level="ok"):
    return render_template("partials/alert.html", message=message, level=level)


def _table(oob=False):
    search = _search()
    customers = api_client.list_customers(search=search)
    return render_template(
        "partials/customer_table.html", customers=customers, search=search, oob=oob
    )


@app.get("/")
def index():
    search = _search()
    customers = []
    error = None
    try:
        customers = api_client.list_customers(search=search)
    except ApiError as exc:
        error = exc.message
    return render_template(
        "index.html",
        customers=customers,
        search=search,
        tiers=LOYALTY_TIERS,
        error=error,
        home_url=HOME_URL,
    )


@app.get("/partials/customers")
def partial_customers():
    try:
        return _table()
    except ApiError as exc:
        return render_template(
            "partials/customer_table.html",
            customers=[],
            search=_search(),
            error=exc.message,
        ), exc.status


@app.get("/customers/<int:customer_id>")
def customer_detail(customer_id):
    try:
        customer = api_client.get_customer(customer_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return render_template("partials/customer_detail.html", customer=customer)


@app.get("/partials/form")
def new_form():
    return render_template("partials/customer_form.html", customer=None, tiers=LOYALTY_TIERS)


@app.get("/partials/form/<int:customer_id>")
def edit_form(customer_id):
    try:
        customer = api_client.get_customer(customer_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return render_template(
        "partials/customer_form.html", customer=customer, tiers=LOYALTY_TIERS
    )


@app.post("/customers")
def create_customer():
    payload = _form_payload(request.form)
    try:
        customer = api_client.create_customer(payload)
    except ApiError as exc:
        return _validation_response(exc, payload)
    return (
        _alert('Created customer "{}".'.format(customer["name"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/customers/<int:customer_id>")
def update_customer(customer_id):
    payload = _form_payload(request.form)
    try:
        customer = api_client.update_customer(customer_id, payload)
    except ApiError as exc:
        return _validation_response(exc, payload, customer_id)
    return (
        _alert('Updated customer "{}".'.format(customer["name"]))
        + _table(oob=True)
        + _blank_form_oob()
    )


@app.post("/customers/<int:customer_id>/delete")
def delete_customer(customer_id):
    try:
        api_client.delete_customer(customer_id)
    except ApiError as exc:
        return _alert(exc.message, "error"), exc.status
    return _alert("Customer #{} deleted.".format(customer_id)) + _table(oob=True)


@app.post("/customers/<int:customer_id>/ai-reward")
def ai_reward(customer_id):
    try:
        outcome = api_client.suggest_reward(customer_id)
    except ApiError as exc:
        return render_template("partials/ai_result.html", error=exc.message)
    return render_template(
        "partials/ai_result.html", outcome=outcome, result=outcome.get("result", {})
    )


def _validation_response(exc, payload, customer_id=None):
    customer = dict(payload)
    if customer_id:
        customer["id"] = customer_id
    form = render_template(
        "partials/customer_form.html",
        customer=customer,
        tiers=LOYALTY_TIERS,
        errors=exc.details or [exc.message],
        oob=True,
    )
    return _alert(exc.message, "error") + form, 200


def _blank_form_oob():
    return render_template(
        "partials/customer_form.html", customer=None, tiers=LOYALTY_TIERS, oob=True
    )


@app.get("/health")
def health():
    downstream = api_client.backend_health()
    healthy = downstream.get("status") == "ok"
    return jsonify({
        "service": "student-3-frontend",
        "student": 3,
        "feature": "Customer Account Management",
        "status": "ok" if healthy else "degraded",
        "backend": downstream,
    }), (200 if healthy else 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "3003")), debug=True)
