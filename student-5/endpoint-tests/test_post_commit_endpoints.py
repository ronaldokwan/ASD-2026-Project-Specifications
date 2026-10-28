"""Release 2 post-commit CI/CD tests: two Reviews and Ratings endpoint functions.

These run against the *live* Student 5 backend/API container that
student-5.yml starts after every push, so they exercise the real HTTP
surface, the database microservice and its SQLite volume.

    1. create_review   POST /api/reviews
    2. update_review   PUT  /api/reviews/<id>

Run locally against a running stack:

    STUDENT5_API_URL=http://localhost:8005 pytest student-5/endpoint-tests -v
"""

import os
import uuid

import pytest
import requests

API_URL = os.getenv("STUDENT5_API_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not API_URL, reason="STUDENT5_API_URL is not set (post-commit endpoint tests)"
)


def _payload(**overrides):
    payload = {
        "product_sku": "sku-ci-{}".format(uuid.uuid4().hex[:6]),
        "user_id": "ci-runner",
        "rating": "4",
        "review": "  Solid build and clear sound, created by the post-commit tests.  ",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def created():
    """Reviews created by a test, deleted afterwards so reruns stay clean."""
    ids = []
    yield ids
    for review_id in ids:
        requests.delete("{}/api/reviews/{}".format(API_URL, review_id), timeout=10)


def _create(created, payload):
    response = requests.post("{}/api/reviews".format(API_URL), json=payload, timeout=10)
    if response.status_code == 201:
        created.append(response.json()["review_id"])
    return response


def _get(review_id):
    return requests.get("{}/api/reviews/{}".format(API_URL, review_id), timeout=10)


# -------------------------------------------------- endpoint 1: create_review
def test_create_review_persists_a_normalised_record(created):
    payload = _payload()
    response = _create(created, payload)

    assert response.status_code == 201
    body = response.json()
    assert body["product_sku"] == payload["product_sku"].upper()   # SKU upper-cased
    assert body["rating"] == 4                                      # "4" coerced to int
    assert body["review"] == payload["review"].strip()              # whitespace trimmed
    stored = _get(body["review_id"])
    assert stored.status_code == 200
    assert stored.json()["user_id"] == "ci-runner"


def test_create_review_rejects_an_out_of_range_rating(created):
    response = _create(created, _payload(rating=6))

    assert response.status_code == 400
    assert "rating must be between 1 and 5" in response.json()["details"]


def test_create_review_rejects_a_too_short_review(created):
    response = _create(created, _payload(review="ok"))

    assert response.status_code == 400
    assert "review must be between 5 and 1000 characters" in response.json()["details"]


def test_create_review_reports_every_missing_field(created):
    response = _create(created, {})

    assert response.status_code == 400
    details = response.json()["details"]
    for field in ("product_sku", "user_id", "rating", "review"):
        assert "{} is required".format(field) in details


# -------------------------------------------------- endpoint 2: update_review
def test_update_review_changes_only_the_supplied_fields(created):
    original = _create(created, _payload()).json()

    response = requests.put(
        "{}/api/reviews/{}".format(API_URL, original["review_id"]),
        json={"rating": 2}, timeout=10,
    )

    assert response.status_code == 200
    stored = _get(original["review_id"]).json()
    assert stored["rating"] == 2
    assert stored["review"] == original["review"]
    assert stored["product_sku"] == original["product_sku"]


def test_update_review_with_invalid_rating_leaves_the_record_unchanged(created):
    original = _create(created, _payload()).json()

    response = requests.put(
        "{}/api/reviews/{}".format(API_URL, original["review_id"]),
        json={"rating": 0}, timeout=10,
    )

    assert response.status_code == 400
    assert _get(original["review_id"]).json()["rating"] == original["rating"]


def test_update_review_with_empty_body_is_rejected(created):
    original = _create(created, _payload()).json()

    response = requests.put(
        "{}/api/reviews/{}".format(API_URL, original["review_id"]),
        json={}, timeout=10,
    )

    assert response.status_code == 400
    assert "no updatable fields supplied" in response.json()["details"]


def test_update_review_of_unknown_id_is_404():
    response = requests.put(
        "{}/api/reviews/{}".format(API_URL, uuid.uuid4()),
        json={"rating": 3}, timeout=10,
    )

    assert response.status_code == 404
