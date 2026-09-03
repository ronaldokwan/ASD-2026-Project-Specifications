"""Database layer and HTTP API tests."""

import pytest

import db as db_module


def valid_customer(email="new.customer@example.test"):
    return {"name": "New Customer", "email": email, "phone": None, "address": None,
            "loyalty_tier": "Bronze", "joined_at": "2026-09-03"}


def test_seeded_customer_count_and_health(database, db_http):
    assert database.count_customers() >= 10
    body = db_http.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["customers"] >= 10


def test_list_and_search_by_name_and_email(database):
    assert len(database.list_customers()) >= 10
    assert any(row["name"] == "Avery Brooks" for row in database.list_customers("avery"))
    assert any("jordan.chen" in row["email"] for row in database.list_customers("JORDAN.CHEN"))


def test_create_read_update_delete(database):
    created = database.create_customer(valid_customer())
    assert database.get_customer(created["id"])["email"] == "new.customer@example.test"
    updated = database.update_customer(created["id"], {"loyalty_tier": "Gold"})
    assert updated["loyalty_tier"] == "Gold"
    database.delete_customer(created["id"])
    with pytest.raises(db_module.NotFound):
        database.get_customer(created["id"])


def test_duplicate_email_is_case_insensitive(database):
    database.create_customer(valid_customer("unique@example.test"))
    with pytest.raises(db_module.Conflict):
        database.create_customer(valid_customer("UNIQUE@example.test"))


def test_database_http_crud_and_missing_customer(db_http):
    created = db_http.post("/customers", json=valid_customer("http@example.test"))
    assert created.status_code == 201
    customer_id = created.get_json()["id"]
    assert db_http.get("/customers/{}".format(customer_id)).status_code == 200
    assert db_http.put("/customers/{}".format(customer_id),
                       json={"loyalty_tier": "Silver"}).get_json()["loyalty_tier"] == "Silver"
    assert db_http.delete("/customers/{}".format(customer_id)).status_code == 200
    assert db_http.get("/customers/{}".format(customer_id)).status_code == 404


def test_database_http_search(db_http):
    assert db_http.get("/customers?search=avery").get_json()["count"] == 1


def test_database_http_duplicate_email(db_http):
    payload = valid_customer("duplicate@example.test")
    assert db_http.post("/customers", json=payload).status_code == 201
    assert db_http.post("/customers", json=payload).status_code == 409
