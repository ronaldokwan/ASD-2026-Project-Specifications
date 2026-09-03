"""HTTP client for the Student 4 database microservice.

The backend never opens the SQLite file itself - it talks to the database
microservice over REST, which is what keeps the three services independently
deployable and separately containerised.
"""

import requests

from .config import Config


class DatabaseError(RuntimeError):
    """The database microservice is unreachable or returned an unexpected error."""


class NotFound(Exception):
    """The requested stock item does not exist."""


class Conflict(Exception):
    """The write would duplicate an existing SKU."""


def _request(method, path, **kwargs):
    """Send one request to the database service and translate HTTP failures."""
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
    """Extract a useful downstream error whether its response is JSON or text."""
    try:
        return response.json().get("error", response.text)
    except ValueError:
        return response.text


# ---------------------------------------------------------------- inventory
def list_stock(**filters):
    """Return stock records matching the supplied optional filters."""
    params = {key: value for key, value in filters.items() if value}
    return _request("GET", "/stock", params=params).get("stock", [])


def list_low_stock(**filters):
    """Return items whose current quantity is at or below their threshold."""
    params = {key: value for key, value in filters.items() if value}
    return _request("GET", "/stock/low", params=params).get("low_stock", [])


def get_stock(stock_id):
    """Fetch one stock item, raising NotFound when it is absent."""
    return _request("GET", "/stock/{}".format(stock_id))


def create_stock(payload):
    """Create a stock item through the database microservice."""
    return _request("POST", "/stock", json=payload)


def update_stock(stock_id, payload):
    """Apply a partial update to an existing stock item."""
    return _request("PUT", "/stock/{}".format(stock_id), json=payload)


def delete_stock(stock_id):
    """Remove a stock item through the database microservice."""
    return _request("DELETE", "/stock/{}".format(stock_id))


def health():
    """Retrieve the database service health report."""
    return _request("GET", "/health")
