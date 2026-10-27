"""Release 2 post-commit CI/CD tests: two Product Catalogue endpoint functions.

These run against the *live* Student 1 backend/API container that
student-1.yml starts after every push, so they exercise the real
frontend-facing HTTP surface, the database microservice and its SQLite volume.

    1. create_product   POST /api/products
    2. update_product   PUT  /api/products/<id>

Run locally against a running stack:

    STUDENT1_API_URL=http://localhost:8001 pytest student-1/endpoint-tests -v
"""

import os
import uuid

import pytest
import requests

API_URL = os.getenv("STUDENT1_API_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not API_URL, reason="STUDENT1_API_URL is not set (post-commit endpoint tests)"
)


def _sku():
    return "SKU-CI-{}".format(uuid.uuid4().hex[:8].upper())


def _payload(**overrides):
    payload = {
        "sku": _sku(),
        "name": "CI Endpoint Speaker",
        "category": "audio",
        "price": "$49.50",
        "description": "Compact speaker created by the student-1 post-commit endpoint tests.",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def created():
    """Products created by a test, deleted afterwards so reruns stay clean."""
    ids = []
    yield ids
    for product_id in ids:
        requests.delete("{}/api/products/{}".format(API_URL, product_id), timeout=10)


def _create(created, payload):
    response = requests.post("{}/api/products".format(API_URL), json=payload, timeout=10)
    if response.status_code == 201:
        created.append(response.json()["id"])
    return response


# ------------------------------------------------- endpoint 1: create_product
def test_create_product_persists_a_normalised_record(created):
    payload = _payload()
    response = _create(created, payload)

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == payload["sku"]
    assert body["category"] == "Audio"     # canonical spelling
    assert body["price"] == 49.5           # currency string coerced
    assert body["status"] == "active"      # default applied
    stored = requests.get("{}/api/products/{}".format(API_URL, body["id"]), timeout=10)
    assert stored.status_code == 200
    assert stored.json()["name"] == payload["name"]


def test_create_product_generates_a_sku_when_omitted(created):
    response = _create(created, _payload(sku="", category="Wearables"))

    assert response.status_code == 201
    assert response.json()["sku"].startswith("SKU-WEA-")


@pytest.mark.parametrize("override, message", [
    ({"category": "Sporting Goods"}, "category must be one of"),
    ({"price": 99999}, "price must be between"),
    ({"name": ""}, "name"),
])
def test_create_product_rejects_invalid_payloads(created, override, message):
    response = _create(created, _payload(**override))

    assert response.status_code == 400
    assert any(message in detail for detail in response.json()["details"])


def test_create_product_rejects_a_duplicate_sku(created):
    payload = _payload()
    assert _create(created, payload).status_code == 201

    duplicate = _create(created, _payload(sku=payload["sku"], name="Clone"))

    assert duplicate.status_code == 409


# ------------------------------------------------- endpoint 2: update_product
def test_update_product_changes_only_the_supplied_fields(created):
    product = _create(created, _payload()).json()

    response = requests.put(
        "{}/api/products/{}".format(API_URL, product["id"]),
        json={"price": 59.95, "status": "draft"}, timeout=10,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == 59.95 and body["status"] == "draft"
    assert body["name"] == product["name"] and body["sku"] == product["sku"]
    stored = requests.get("{}/api/products/{}".format(API_URL, product["id"]), timeout=10)
    assert stored.json()["price"] == 59.95


def test_update_product_rejects_invalid_values_and_keeps_the_record(created):
    product = _create(created, _payload()).json()
    url = "{}/api/products/{}".format(API_URL, product["id"])

    response = requests.put(url, json={"price": 0}, timeout=10)

    assert response.status_code == 400
    assert requests.get(url, timeout=10).json()["price"] == product["price"]


def test_update_product_with_no_fields_is_rejected(created):
    product = _create(created, _payload()).json()

    response = requests.put(
        "{}/api/products/{}".format(API_URL, product["id"]), json={}, timeout=10
    )

    assert response.status_code == 400


def test_update_product_unknown_id_is_404():
    response = requests.put(
        "{}/api/products/987654321".format(API_URL), json={"price": 10}, timeout=10
    )

    assert response.status_code == 404
