"""HTTP client for the Student 3 database microservice."""

import requests

from .config import Config


class DatabaseError(RuntimeError):
    """The database API is unavailable or returned an unexpected error."""


class NotFound(Exception):
    """The requested customer does not exist."""


class Conflict(Exception):
    """The email address already belongs to another customer."""


def _error_of(response):
    try:
        return response.json().get("error", response.text)
    except ValueError:
        return response.text


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
    return response.json() if response.content else {}


def list_customers(search=None):
    params = {"search": search} if search else {}
    return _request("GET", "/customers", params=params).get("customers", [])


def get_customer(customer_id):
    return _request("GET", "/customers/{}".format(customer_id))


def create_customer(payload):
    return _request("POST", "/customers", json=payload)


def update_customer(customer_id, payload):
    return _request("PUT", "/customers/{}".format(customer_id), json=payload)


def delete_customer(customer_id):
    return _request("DELETE", "/customers/{}".format(customer_id))


def health():
    return _request("GET", "/health")
