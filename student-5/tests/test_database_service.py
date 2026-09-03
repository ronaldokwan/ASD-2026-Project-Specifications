"""Student 5 - database microservice tests (SQLite CRUD + seed data)."""

import pytest

import db as db_module


# ------------------------------------------------------------------- seeding
def test_seed_contains_at_least_ten_records(database):
    """every database table holds a minimum of ten records."""
    assert database.count_reviews() >= 10


def test_seed_covers_several_products(database):
    products = {row["product_sku"] for row in database.list_reviews()}
    assert len(products) >= 3


def test_seed_ratings_are_between_one_and_five(database):
    ratings = {row["rating"] for row in database.list_reviews()}
    assert ratings and all(1 <= r <= 5 for r in ratings)


# ---------------------------------------------------------------------- CRUD
def test_create_read_update_delete(database):
    created = database.create_review(
        {
            "product_sku": "SKU-TST-9001",
            "user_id": "test-user",
            "rating": 3,
            "review": "A review used in tests.",
        }
    )
    assert created["review_id"]
    assert created["created_at"]

    fetched = database.get_review(created["review_id"])
    assert fetched["product_sku"] == "SKU-TST-9001"

    updated = database.update_review(created["review_id"], {"rating": 5})
    assert updated["rating"] == 5
    assert updated["review"] == "A review used in tests."  # untouched fields survive

    database.delete_review(created["review_id"])
    with pytest.raises(db_module.NotFound):
        database.get_review(created["review_id"])


def test_unknown_id_raises_not_found(database):
    with pytest.raises(db_module.NotFound):
        database.get_review("does-not-exist")


# ------------------------------------------------------------------ querying
def test_filter_by_product_and_rating(database):
    audio = database.list_reviews(product_sku="SKU-AUD-1001")
    assert audio and all(r["product_sku"] == "SKU-AUD-1001" for r in audio)

    five_star = database.list_reviews(rating=5)
    assert all(r["rating"] == 5 for r in five_star)


def test_sort_by_rating(database):
    ratings = [r["rating"] for r in database.list_reviews(sort="rating_desc")]
    assert ratings == sorted(ratings, reverse=True)


def test_product_stats_ground_the_ai(database):
    stats = database.product_stats("SKU-AUD-1001")
    assert stats["review_count"] >= 2
    assert stats["rating_distribution"]
    assert stats["sample"]


def test_product_stats_for_unknown_product_is_empty(database):
    stats = database.product_stats("SKU-DOES-NOT-EXIST")
    assert stats["review_count"] == 0
    assert stats["sample"] == []


# ----------------------------------------------------------- HTTP data layer
def test_health_endpoint(db_client_http):
    body = db_client_http.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["reviews"] >= 10


def test_reviews_endpoint_supports_product_filter(db_client_http):
    body = db_client_http.get("/reviews?product_sku=SKU-AUD-1001").get_json()
    assert body["count"] >= 2


def test_http_crud_round_trip(db_client_http):
    created = db_client_http.post(
        "/reviews",
        json={
            "product_sku": "SKU-TST-9002",
            "user_id": "http-test-user",
            "rating": 4,
            "review": "Created via REST.",
        },
    )
    assert created.status_code == 201
    review_id = created.get_json()["review_id"]

    assert db_client_http.get("/reviews/{}".format(review_id)).status_code == 200

    updated = db_client_http.put("/reviews/{}".format(review_id), json={"rating": 2})
    assert updated.get_json()["rating"] == 2

    assert db_client_http.delete("/reviews/{}".format(review_id)).status_code == 200
    assert db_client_http.get("/reviews/{}".format(review_id)).status_code == 404


def test_http_stats_endpoint(db_client_http):
    body = db_client_http.get("/stats/product/SKU-AUD-1001").get_json()
    assert body["review_count"] >= 2
    assert 1 <= body["avg_rating"] <= 5
