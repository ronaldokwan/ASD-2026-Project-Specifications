"""HTTP client for the Student 5 backend/API microservice.

The frontend microservice holds no business logic and no database access - it
renders HTML and calls the API, which is what makes the three services
independently deployable.
"""

import os

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://student-5-backend:8005").rstrip("/")
TIMEOUT = int(os.getenv("BACKEND_TIMEOUT", "15"))
AI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))


class ApiError(Exception):
    """Carries a human-readable message for display in the UI."""

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
        raise ApiError("Reviews and Ratings API is unreachable ({}).".format(exc), 503) from exc

    try:
        body = response.json() if response.content else {}
    except ValueError:
        raise ApiError("The API returned an unreadable response.", response.status_code)

    if response.status_code >= 400:
        raise ApiError(
            body.get("error", "Request failed with status {}".format(response.status_code)),
            response.status_code,
            body.get("details"),
        )
    return body


def list_reviews(**filters):
    params = {key: value for key, value in filters.items() if value}
    return _call("GET", "/api/reviews", params=params).get("reviews", [])


def get_review(review_id):
    return _call("GET", "/api/reviews/{}".format(review_id))


def create_review(payload):
    return _call("POST", "/api/reviews", json=payload)


def update_review(review_id, payload):
    return _call("PUT", "/api/reviews/{}".format(review_id), json=payload)


def delete_review(review_id):
    return _call("DELETE", "/api/reviews/{}".format(review_id))


def list_products():
    return _call("GET", "/api/products").get("products", [])


def generate_summary(product_sku):
    return _call(
        "POST",
        "/api/reviews/ai",
        timeout=AI_TIMEOUT,
        json={"product_sku": product_sku},
    )


def backend_health():
    try:
        return _call("GET", "/health")
    except ApiError as exc:
        return {"status": "unreachable", "error": exc.message}
