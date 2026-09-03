"""HTTP client for the Student 3 business API."""

import os

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://student-3-backend:8003").rstrip("/")
TIMEOUT = int(os.getenv("BACKEND_TIMEOUT", "15"))
AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))


class ApiError(Exception):
    def __init__(self, message, status=502, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details or []


def _call(method, path, timeout=None, **kwargs):
    url = "{}{}".format(BACKEND_URL, path)
    try:
        response = requests.request(method, url, timeout=timeout or TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ApiError("Customer Account API is unreachable ({}).".format(exc), 503) from exc
    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        raise ApiError("The API returned an unreadable response.", response.status_code) from exc
    if response.status_code >= 400:
        raise ApiError(
            body.get("error", "Request failed with status {}".format(response.status_code)),
            response.status_code,
            body.get("details") or ([body["detail"]] if body.get("detail") else []),
        )
    return body


def list_customers(search=None):
    params = {"search": search} if search else {}
    return _call("GET", "/api/customers", params=params).get("customers", [])


def get_customer(customer_id):
    return _call("GET", "/api/customers/{}".format(customer_id))


def create_customer(payload):
    return _call("POST", "/api/customers", json=payload)


def update_customer(customer_id, payload):
    return _call("PUT", "/api/customers/{}".format(customer_id), json=payload)


def delete_customer(customer_id):
    return _call("DELETE", "/api/customers/{}".format(customer_id))


def suggest_reward(customer_id):
    return _call(
        "POST", "/api/customers/{}/ai-reward".format(customer_id), timeout=AI_TIMEOUT
    )


def backend_health():
    try:
        return _call("GET", "/health")
    except ApiError as exc:
        return {"status": "unreachable", "error": exc.message}
