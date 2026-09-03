"""Student 1 - backend/API microservice tests.

The database and AI-Mode hops are stubbed, so these tests cover the API
contract, the validation rules and the AI request the backend builds.
"""

import pytest

from app import ai_agent, db_client
from app.validation import ValidationError, clean_product


# -------------------------------------------------------------------- health
def test_health_reports_the_feature(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "ai_mode_health", lambda: {"status": "ok"})
    body = backend.get("/health").get_json()
    assert body["student"] == 1
    assert body["feature"] == "Product Catalogue"
    assert body["status"] == "ok"


# ---------------------------------------------------------------------- READ
def test_list_products(backend, fake_db):
    body = backend.get("/api/products").get_json()
    assert body["count"] == 2
    assert {p["sku"] for p in body["products"]} == {"SKU-AUD-1001", "SKU-HOM-3001"}


def test_list_products_filtered_by_sku(backend, fake_db):
    body = backend.get("/api/products?sku=SKU-AUD-1001").get_json()
    assert body["count"] == 1


def test_get_one_product(backend, fake_db):
    assert backend.get("/api/products/1").get_json()["sku"] == "SKU-AUD-1001"


def test_get_missing_product_returns_404(backend, fake_db):
    response = backend.get("/api/products/404")
    assert response.status_code == 404
    assert "error" in response.get_json()


# -------------------------------------------------------------------- CREATE
def test_create_product(backend, fake_db):
    response = backend.post("/api/products", json={
        "sku": "sku-new-1", "name": "New Product", "category": "Audio",
        "price": "$59.99", "description": "A new product.",
    })
    assert response.status_code == 201
    body = response.get_json()
    assert body["sku"] == "SKU-NEW-1"    # normalised to upper case
    assert body["price"] == 59.99        # currency string coerced
    assert body["status"] == "active"    # default applied


@pytest.mark.parametrize("payload, expected_error", [
    ({"sku": "SKU-1", "name": "Bad category", "category": "Sporting Goods", "price": 10},
     "category must be one of"),
    ({"sku": "SKU-1", "category": "Audio", "price": 10}, "name is required"),
    ({"sku": "SKU-1", "name": "No price", "category": "Audio"}, "price is required"),
    ({"sku": "SKU-1", "name": "Bad price", "category": "Audio", "price": "abc"},
     "price must be a number"),
    ({"sku": "SKU-1", "name": "Too dear", "category": "Audio", "price": 99999},
     "price must be between"),
    ({"sku": "!!", "name": "Bad sku", "category": "Audio", "price": 10}, "sku must be"),
    ({"sku": "SKU-1", "name": "Bad status", "category": "Audio", "price": 10,
      "status": "on-sale"}, "status must be one of"),
])
def test_create_rejects_invalid_payloads(backend, fake_db, payload, expected_error):
    response = backend.post("/api/products", json=payload)
    assert response.status_code == 400
    assert any(expected_error in detail for detail in response.get_json()["details"])


def test_create_duplicate_sku_returns_409(backend, fake_db):
    response = backend.post("/api/products", json={
        "sku": "SKU-AUD-1001", "name": "Clone", "category": "Audio", "price": 10,
    })
    assert response.status_code == 409


# -------------------------------------------------------------- UPDATE/DELETE
def test_partial_update(backend, fake_db):
    body = backend.put("/api/products/1", json={"price": 149.0}).get_json()
    assert body["price"] == 149.0
    assert body["name"] == "Aurora Wireless Headphones"


def test_update_with_no_fields_is_rejected(backend, fake_db):
    assert backend.put("/api/products/1", json={}).status_code == 400


def test_delete_product(backend, fake_db):
    assert backend.delete("/api/products/1").get_json() == {"deleted": 1}
    assert backend.get("/api/products/1").status_code == 404


def test_database_outage_returns_503(backend, monkeypatch):
    def boom(**_kwargs):
        raise db_client.DatabaseError("connection refused")

    monkeypatch.setattr(db_client, "list_products", boom)
    response = backend.get("/api/products")
    assert response.status_code == 503
    assert "database microservice unavailable" in response.get_json()["error"]


# ------------------------------------------------------------------- AI-mode
def test_ai_endpoint_returns_result_and_trace(backend, fake_db, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json

        class Response:
            status_code = 200
            content = b"{}"

            @staticmethod
            def json():
                return {
                    "ok": True,
                    "result": {"description": "Great headphones for commuting.", "price": 179.0},
                    "attempts": 1,
                    "fallback_used": False,
                    "model": "qwen2.5:0.5b",
                    "elapsed_ms": 900,
                    "trace": [{"step": "Plan"}, {"step": "Act"}, {"step": "Observe"}],
                }

        return Response()

    monkeypatch.setattr(ai_agent.requests, "post", fake_post)

    response = backend.post("/api/products/ai",
                            json={"name": "Aurora Headphones", "category": "Audio"})
    body = response.get_json()

    assert response.status_code == 200
    assert body["result"]["price"] == 179.0
    assert [step["step"] for step in body["trace"]] == ["Plan", "Act", "Observe"]

    # The request must be grounded in real catalogue facts (the Plan step) and
    # must declare the guardrails used by the Observe step.
    payload = captured["payload"]
    assert payload["context"]["category_avg_price"] == 199.95
    assert payload["output_schema"]["price"]["max"] == 9999.0
    assert payload["fallback"]["description"]


def test_ai_endpoint_requires_name_and_category(backend, fake_db):
    assert backend.post("/api/products/ai", json={"name": "x"}).status_code == 400


def test_ai_service_outage_returns_503(backend, fake_db, monkeypatch):
    def boom(*_args, **_kwargs):
        raise ai_agent.requests.RequestException("connection refused")

    monkeypatch.setattr(ai_agent.requests, "post", boom)
    response = backend.post("/api/products/ai", json={"name": "Widget", "category": "Audio"})
    assert response.status_code == 503
    assert "AI-Mode" in response.get_json()["error"]


def test_ai_fallback_is_grounded_in_the_category_average(backend, fake_db):
    context = ai_agent.build_context("Widget", "Audio")
    fallback = ai_agent._fallback("Widget", "Audio", context)
    assert fallback["price"] == 199.95
    assert "Widget" in fallback["description"]


# ------------------------------------------------------------- validation unit
def test_clean_product_normalises_values():
    cleaned = clean_product({"sku": " sku-abc ", "name": "  Thing ", "category": "Audio",
                             "price": "1,299.00"})
    assert cleaned["sku"] == "SKU-ABC"
    assert cleaned["name"] == "Thing"
    assert cleaned["price"] == 1299.0


def test_clean_product_partial_requires_a_field():
    with pytest.raises(ValidationError):
        clean_product({}, partial=True)


# ------------------------------------------------- generated SKUs + categories
def test_create_without_sku_generates_one_for_the_category(backend, fake_db):
    """Omitting the SKU continues the category's existing numbering."""
    response = backend.post("/api/products", json={
        "name": "Nimbus Earbuds", "category": "Audio", "price": 79.00,
    })
    assert response.status_code == 201
    # The fake starts with SKU-AUD-1001, so the next Audio SKU is 1002.
    assert response.get_json()["sku"] == "SKU-AUD-1002"


def test_generated_sku_uses_the_category_block_when_empty(backend, fake_db):
    """A category with no products yet starts at its own block, not 0001."""
    response = backend.post("/api/products", json={
        "name": "Trail Watch", "category": "Wearables", "price": 149.00,
    })
    assert response.status_code == 201
    assert response.get_json()["sku"] == "SKU-WEA-4001"


def test_supplied_sku_is_still_honoured(backend, fake_db):
    """Supplier- or ERP-assigned SKUs must survive; generation is a fallback."""
    response = backend.post("/api/products", json={
        "sku": "vendor-99", "name": "Third Party", "category": "Home", "price": 25.00,
    })
    assert response.status_code == 201
    assert response.get_json()["sku"] == "VENDOR-99"


def test_category_is_normalised_to_the_configured_spelling(backend, fake_db):
    """Casing is fixed on write so category_stats() sees one grouping key."""
    response = backend.post("/api/products", json={
        "name": "Desk Lamp", "category": "home", "price": 30.00,
    })
    assert response.status_code == 201
    assert response.get_json()["category"] == "Home"


def test_categories_endpoint_exposes_the_closed_set(backend, fake_db):
    body = backend.get("/api/categories").get_json()
    assert "categories" in body                      # unchanged for consumers
    assert body["valid_categories"] == ["Audio", "Computing", "Home", "Wearables"]


def test_next_sku_previews_without_creating(backend, fake_db):
    """The preview must not consume the number it reports."""
    before = len(fake_db.rows)
    body = backend.get("/api/products/next-sku?category=Audio").get_json()
    assert body["sku"] == "SKU-AUD-1002"
    assert len(fake_db.rows) == before

    # ...and the create that follows is assigned exactly what was previewed.
    created = backend.post("/api/products", json={
        "name": "Nimbus Earbuds", "category": "Audio", "price": 79.00,
    }).get_json()
    assert created["sku"] == body["sku"]


def test_next_sku_normalises_the_category(backend, fake_db):
    body = backend.get("/api/products/next-sku?category=home").get_json()
    assert body["category"] == "Home"
    assert body["sku"] == "SKU-HOM-3002"


def test_next_sku_rejects_an_unknown_category(backend, fake_db):
    response = backend.get("/api/products/next-sku?category=Sporting+Goods")
    assert response.status_code == 400
    assert any("category must be one of" in detail
               for detail in response.get_json()["details"])


def test_next_sku_does_not_shadow_the_numeric_product_route(backend, fake_db):
    """/api/products/next-sku must not be parsed as a product id."""
    assert backend.get("/api/products/1").get_json()["id"] == 1
