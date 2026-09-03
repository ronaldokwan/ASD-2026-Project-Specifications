"""HTTP client for the Student 5 database microservice.

The backend never opens the SQLite file itself - it talks to the database
microservice over REST, which is what keeps the three microservices
independently deployable and separately containerised.
"""

import requests

from .config import Config


class DatabaseError(RuntimeError):
    """The database microservice is unreachable or returned an unexpected error."""


class NotFound(Exception):
    """The requested review does not exist."""


def _request(method, path, **kwargs):
    url = "{}{}".format(Config.DATABASE_URL, path)
    try:
        response = requests.request(method, url, timeout=Config.DATABASE_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise DatabaseError("database microservice unreachable at {}: {}".format(url, exc)) from exc

    if response.status_code == 404:
        raise NotFound(_error_of(response))
    if response.status_code >= 400:
        raise DatabaseError("database microservice error {}: {}".format(
            response.status_code, _error_of(response)))

    if not response.content:
        return {}
    return response.json()


def _error_of(response):
    try:
        return response.json().get("error", response.text)
    except ValueError:
        return response.text


# ------------------------------------------------------------------ reviews
def list_reviews(**filters):
    params = {key: value for key, value in filters.items() if value}
    return _request("GET", "/reviews", params=params).get("reviews", [])


def get_review(review_id):
    return _request("GET", "/reviews/{}".format(review_id))


def create_review(payload):
    return _request("POST", "/reviews", json=payload)


def update_review(review_id, payload):
    return _request("PUT", "/reviews/{}".format(review_id), json=payload)


def delete_review(review_id):
    return _request("DELETE", "/reviews/{}".format(review_id))


def product_stats(product_sku):
    return _request("GET", "/stats/product/{}".format(product_sku))


def health():
    return _request("GET", "/health")
