"""Student 4 - database microservice tests (SQLite stock CRUD + seed data)."""

import pytest

import db as db_module


def _stock(sku="SKU-TST-9001"):
    """Build a valid reusable stock payload for database and HTTP CRUD tests."""
    return {"sku": sku, "name": "Test Widget", "category": "Audio", "location": "Shelf A4",
            "quantity": 12, "restock_threshold": 20, "stock_level": "low"}


# Seed data supports a populated inventory demonstration across categories.
def test_seed_contains_at_least_ten_stock_records(database):
    assert database.count_stock() >= 10
    assert len({row["category"] for row in database.list_stock()}) >= 3


# Direct database functions support the complete inventory record lifecycle.
def test_create_read_update_delete_stock(database):
    created = database.create_stock(_stock())
    assert created["id"] and created["last_restocked"]
    assert database.get_stock(created["id"])["sku"] == "SKU-TST-9001"
    updated = database.update_stock(created["id"], {"quantity": 30})
    assert updated["quantity"] == 30
    database.delete_stock(created["id"])
    with pytest.raises(db_module.NotFound):
        database.get_stock(created["id"])


# The SQLite constraints are exposed as domain exceptions to callers.
def test_duplicate_sku_and_unknown_id(database):
    existing = database.list_stock()[0]
    with pytest.raises(db_module.Conflict):
        database.create_stock(_stock(existing["sku"]))
    with pytest.raises(db_module.NotFound):
        database.get_stock(999999)


# Inventory reads support low-stock detection, search, and quantity sorting.
def test_stock_queries(database):
    low = database.list_low_stock()
    assert low and all(item["quantity"] <= item["restock_threshold"] for item in low)
    assert database.list_stock(search="Headphones")
    quantities = [item["quantity"] for item in database.list_stock(sort="qty_asc")]
    assert quantities == sorted(quantities)


# The database microservice exposes the same operations over HTTP for the API.
def test_http_stock_crud_round_trip(db_client_http):
    assert db_client_http.get("/health").get_json()["stock_items"] >= 10
    created = db_client_http.post("/stock", json=_stock("SKU-TST-9002"))
    assert created.status_code == 201
    stock_id = created.get_json()["id"]
    assert db_client_http.put("/stock/{}".format(stock_id), json={"quantity": 25}).get_json()["quantity"] == 25
    assert db_client_http.delete("/stock/{}".format(stock_id)).status_code == 200