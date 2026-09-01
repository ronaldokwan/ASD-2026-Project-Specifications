"""HTTP client for the Student 1 database microservice.

The backend never opens the SQLite file itself - it talks to the database
microservice over REST, which is what keeps the three services independently
deployable and separately containerised.
"""

import requests

from .config import Config


class DatabaseError(RuntimeError):
    """The database microservice is unreachable or returned an unexpected error."""


class NotFound(Exception):
    """The requested product does not exist."""


class Conflict(Exception):
    """The write would duplicate an existing SKU."""


def _request(method, path, **kwargs):
    url = "{}{}".format(Config.DATABASE_URL, path)
    try:
        response = requests.request(method, url, timeout=Config.DATABASE_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise DatabaseError("database microservice unreachable at {}: {}".format(url, exc)) from exc

    if response.status_code == 404:
        raise NotFound(_error_of(response))
    if response.status_code == 409:
        raise Conflict(_error_of(response))
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


# ---------------------------------------------------------------- catalogue
def list_products(**filters):
    params = {key: value for key, value in filters.items() if value}
    return _request("GET", "/products", params=params).get("products", [])


def get_product(product_id):
    return _request("GET", "/products/{}".format(product_id))


def create_product(payload):
    return _request("POST", "/products", json=payload)


def update_product(product_id, payload):
    return _request("PUT", "/products/{}".format(product_id), json=payload)


def delete_product(product_id):
    return _request("DELETE", "/products/{}".format(product_id))


def list_categories():
    return _request("GET", "/categories").get("categories", [])


def category_stats(category):
    return _request("GET", "/stats/category/{}".format(category))


def health():
    return _request("GET", "/health")
