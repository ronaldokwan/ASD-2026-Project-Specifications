"""Student 1 - database microservice tests (SQLite CRUD + seed data)."""

import pytest

import db as db_module


# ------------------------------------------------------------------- seeding
def test_seed_contains_at_least_ten_records(database):
    """every database table holds a minimum of ten records."""
    assert database.count_products() >= 10


def test_seed_covers_several_categories(database):
    categories = {row["category"] for row in database.list_products()}
    assert len(categories) >= 3


# ---------------------------------------------------------------------- CRUD
def test_create_read_update_delete(database):
    created = database.create_product(
        {
            "sku": "SKU-TST-9001",
            "name": "Test Product",
            "description": "A product used in tests.",
            "category": "Audio",
            "price": 12.5,
            "status": "draft",
        }
    )
    assert created["id"]
    assert created["created_at"]

    fetched = database.get_product(created["id"])
    assert fetched["sku"] == "SKU-TST-9001"

    updated = database.update_product(
        created["id"], {"price": 15.0, "status": "active"}
    )
    assert updated["price"] == 15.0
    assert updated["status"] == "active"
    assert updated["name"] == "Test Product"  # untouched fields survive

    database.delete_product(created["id"])
    with pytest.raises(db_module.NotFound):
        database.get_product(created["id"])


def test_duplicate_sku_is_rejected(database):
    existing = database.list_products()[0]
    with pytest.raises(db_module.Conflict):
        database.create_product(
            {
                "sku": existing["sku"],
                "name": "Clone",
                "description": "",
                "category": "Audio",
                "price": 10.0,
                "status": "active",
            }
        )


def test_unknown_id_raises_not_found(database):
    with pytest.raises(db_module.NotFound):
        database.get_product(999999)


# ------------------------------------------------------------------ querying
def test_filter_by_category_and_status(database):
    audio = database.list_products(category="Audio")
    assert audio and all(p["category"] == "Audio" for p in audio)

    archived = database.list_products(status="archived")
    assert all(p["status"] == "archived" for p in archived)


def test_search_matches_name_and_sku(database):
    assert database.list_products(search="Headphones")
    assert database.list_products(search="SKU-COM")


def test_sort_by_price(database):
    prices = [p["price"] for p in database.list_products(sort="price_asc")]
    assert prices == sorted(prices)


def _stamped(database, sku, name, created_at, updated_at):
    """Insert a row with exact timestamps.

    Written straight to SQLite because the updated_at trigger fires on UPDATE
    (not INSERT), so this is the only way to pin both stamps for a test.
    """
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO products (sku, name, description, category, price, "
            "status, created_at, updated_at) VALUES (?,?,'',?,?,?,?,?)",
            (sku, name, "Audio", 10.0, "active", created_at, updated_at),
        )


def test_default_sort_ranks_by_the_latest_change(database):
    """No ?sort= means the rows that changed most recently come first."""
    _stamped(database, "SKU-TST-8001", "Old But Edited",
             created_at="2030-01-01 00:00:00", updated_at="2030-03-01 00:00:00")
    _stamped(database, "SKU-TST-8002", "New But Untouched",
             created_at="2030-02-01 00:00:00", updated_at="2030-02-01 00:00:00")

    assert [p["sku"] for p in database.list_products()][:2] == [
        "SKU-TST-8001",
        "SKU-TST-8002",
    ]


def test_default_sort_counts_creation_as_a_change(database):
    """A row created after its last edit is ranked on created_at, not updated_at."""
    _stamped(database, "SKU-TST-8003", "Created Later",
             created_at="2030-04-01 00:00:00", updated_at="2029-01-01 00:00:00")

    assert database.list_products()[0]["sku"] == "SKU-TST-8003"


def test_name_sort_ignores_letter_case(database):
    """Lower-case names interleave instead of being dumped after every capital."""
    _stamped(database, "SKU-TST-8004", "apple Dock",
             created_at="2026-01-01 00:00:00", updated_at="2026-01-01 00:00:00")
    _stamped(database, "SKU-TST-8005", "Banana Stand",
             created_at="2026-01-01 00:00:00", updated_at="2026-01-01 00:00:00")

    names = [p["name"] for p in database.list_products(sort="name")]
    assert names == sorted(names, key=str.lower)
    assert names.index("apple Dock") < names.index("Banana Stand")


def test_category_stats_ground_the_ai(database):
    stats = database.category_stats("Audio")
    assert stats["product_count"] >= 3
    assert stats["min_price"] <= stats["avg_price"] <= stats["max_price"]
    assert stats["sample"]


# ----------------------------------------------------------- HTTP data layer
def test_health_endpoint(db_client_http):
    body = db_client_http.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["products"] >= 10


def test_products_endpoint_supports_sku_filter(db_client_http):
    body = db_client_http.get("/products?sku=SKU-AUD-1001").get_json()
    assert body["count"] == 1
    assert body["products"][0]["name"] == "Aurora Wireless Headphones"


def test_http_crud_round_trip(db_client_http):
    created = db_client_http.post(
        "/products",
        json={
            "sku": "SKU-TST-9002",
            "name": "HTTP Product",
            "description": "via REST",
            "category": "Home",
            "price": 20.0,
            "status": "active",
        },
    )
    assert created.status_code == 201
    product_id = created.get_json()["id"]

    assert db_client_http.get("/products/{}".format(product_id)).status_code == 200

    updated = db_client_http.put(
        "/products/{}".format(product_id), json={"price": 25.0}
    )
    assert updated.get_json()["price"] == 25.0

    assert db_client_http.delete("/products/{}".format(product_id)).status_code == 200
    assert db_client_http.get("/products/{}".format(product_id)).status_code == 404


def test_http_duplicate_sku_returns_409(db_client_http):
    payload = {
        "sku": "SKU-AUD-1001",
        "name": "Clone",
        "description": "",
        "category": "Audio",
        "price": 10.0,
        "status": "active",
    }
    assert db_client_http.post("/products", json=payload).status_code == 409
