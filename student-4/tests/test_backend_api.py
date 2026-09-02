"""Student 4 - backend/API microservice tests."""

import pytest

from app import ai_agent, db_client
from app.validation import ValidationError, clean_stock


def test_health_reports_the_feature(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "ai_mode_health", lambda: {"status": "ok"})
    body = backend.get("/health").get_json()
    assert body["student"] == 4
    assert body["feature"] == "Inventory and Stock"
    assert body["status"] == "ok"


def test_list_stock_and_low_stock(backend, fake_db):
    stock = backend.get("/api/stock").get_json()
    low = backend.get("/api/stock/low").get_json()
    assert stock["count"] == 2
    assert stock["stock"][0]["sku"] == "SKU-AUD-1001"
    assert low["count"] == 1
    assert low["low_stock"][0]["stock_level"] == "low"


def test_get_missing_stock_returns_404(backend, fake_db):
    assert backend.get("/api/stock/404").status_code == 404


def test_create_stock_normalises_values(backend, fake_db):
    response = backend.post("/api/stock", json={
        "sku": " sku-new-1 ", "name": "New Widget", "category": "Audio",
        "location": "Shelf A4", "quantity": "12", "restock_threshold": "20",
        "stock_level": "low",
    })
    assert response.status_code == 201
    assert response.get_json()["sku"] == "SKU-NEW-1"
    assert response.get_json()["quantity"] == 12


@pytest.mark.parametrize("payload, expected_error", [
    ({"name": "No SKU"}, "sku is required"),
    ({"sku": "SKU-1", "name": "Name", "category": "Audio", "location": "A1", "quantity": "x", "restock_threshold": 5}, "quantity must be an integer"),
    ({"sku": "SKU-1", "name": "Name", "category": "Audio", "location": "A1", "quantity": 1, "restock_threshold": 5, "stock_level": "empty"}, "stock_level must be one of"),
])
def test_create_rejects_invalid_stock(backend, fake_db, payload, expected_error):
    response = backend.post("/api/stock", json=payload)
    assert response.status_code == 400
    assert any(expected_error in detail for detail in response.get_json()["details"])


def test_partial_update_and_delete(backend, fake_db):
    updated = backend.put("/api/stock/1", json={"quantity": 50}).get_json()
    assert updated["quantity"] == 50
    assert backend.delete("/api/stock/1").get_json() == {"deleted": 1}
    assert backend.get("/api/stock/1").status_code == 404


def test_restock_recommendation_returns_trace(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "recommend_restocking", lambda category: {
        "ok": True, "result": {"recommendations": []}, "trace": [{"step": "Plan"}],
    })
    body = backend.post("/api/stock/recommend", json={"category": "Audio"}).get_json()
    assert body["ok"] is True
    assert body["trace"][0]["step"] == "Plan"


def test_recommendation_requires_category(backend, fake_db):
    assert backend.post("/api/stock/recommend", json={}).status_code == 400


def test_clean_stock_partial_requires_a_field():
    with pytest.raises(ValidationError):
        clean_stock({}, partial=True)