"""Student 4 - backend/API microservice tests."""

from types import SimpleNamespace

import pytest

from app import ai_agent, db_client, mcp_client, rag_client
from app.config import Config
from app.validation import ValidationError, clean_stock


# Health responses identify the Student 4 feature and surface dependency state.
def test_health_reports_the_feature(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "ai_mode_health", lambda: {"status": "ok"})
    monkeypatch.setattr(mcp_client, "health", lambda: {"status": "ok"})
    monkeypatch.setattr(rag_client, "health", lambda: {"status": "ok"})
    body = backend.get("/health").get_json()
    assert body["student"] == 4
    assert body["feature"] == "Inventory and Stock"
    assert body["status"] == "ok"
    assert body["mcp_server"]["status"] == "ok"
    assert body["rag_server"]["status"] == "ok"


# Read routes provide both the complete inventory and the low-stock subset.
def test_list_stock_and_low_stock(backend, fake_db):
    stock = backend.get("/api/stock").get_json()
    low = backend.get("/api/stock/low").get_json()
    assert stock["count"] == 2
    assert stock["stock"][0]["sku"] == "SKU-AUD-1001"
    assert low["count"] == 1
    assert low["low_stock"][0]["stock_level"] == "low"


# Missing ids must be represented as HTTP 404 rather than an internal error.
def test_get_missing_stock_returns_404(backend, fake_db):
    assert backend.get("/api/stock/404").status_code == 404


# Create requests are normalised before passing to the database service.
def test_create_stock_normalises_values(backend, fake_db):
    response = backend.post("/api/stock", json={
        "sku": " sku-new-1 ", "name": "New Widget", "category": "Audio",
        "location": "Shelf A4", "quantity": "12", "restock_threshold": "20",
        "stock_level": "low",
    })
    assert response.status_code == 201
    assert response.get_json()["sku"] == "SKU-NEW-1"
    assert response.get_json()["quantity"] == 12


def test_create_stock_upserts_rag_document(backend, fake_db, monkeypatch):
    synced = []
    monkeypatch.setattr(rag_client, "sync_stock", synced.append)
    response = backend.post("/api/stock", json={
        "sku": "SKU-NEW-2", "name": "New Widget", "category": "Audio",
        "location": "Shelf A4", "quantity": 12, "restock_threshold": 20,
    })
    assert response.status_code == 201
    assert synced[0]["sku"] == "SKU-NEW-2"


# Invalid payloads should return useful API validation details to the frontend.
@pytest.mark.parametrize("payload, expected_error", [
    ({"name": "No SKU"}, "sku is required"),
    ({"sku": "SKU-1", "name": "Name", "category": "Audio", "location": "A1", "quantity": "x", "restock_threshold": 5}, "quantity must be an integer"),
    ({"sku": "SKU-1", "name": "Name", "category": "Audio", "location": "A1", "quantity": 1, "restock_threshold": 5, "stock_level": "empty"}, "stock_level must be one of"),
])
def test_create_rejects_invalid_stock(backend, fake_db, payload, expected_error):
    response = backend.post("/api/stock", json=payload)
    assert response.status_code == 400
    assert any(expected_error in detail for detail in response.get_json()["details"])


# Updates preserve the REST contract and deletes make records unavailable.
def test_partial_update_and_delete(backend, fake_db):
    updated = backend.put("/api/stock/1", json={"quantity": 50}).get_json()
    assert updated["quantity"] == 50
    assert backend.delete("/api/stock/1").get_json() == {"deleted": 1}
    assert backend.get("/api/stock/1").status_code == 404


# The AI endpoint returns the agent workflow trace for the interface to display.
def test_restock_recommendation_returns_trace(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "recommend_restocking", lambda category: {
        "ok": True, "result": {"recommendations": []}, "trace": [{"step": "Plan"}],
    })
    body = backend.post("/api/stock/recommend", json={"category": "Audio"}).get_json()
    assert body["ok"] is True
    assert body["trace"][0]["step"] == "Plan"


# A recommendation cannot be grounded without a category.
def test_recommendation_requires_category(backend, fake_db):
    assert backend.post("/api/stock/recommend", json={}).status_code == 400


def test_mcp_stock_check_returns_validated_result(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(mcp_client, "_execute", lambda arguments: {
        "tool": "check_stock_reorder",
        "sku": arguments["sku"],
        "reorder_required": True,
        "quantity": 18,
        "restock_threshold": 25,
        "recommended_order_quantity": 32,
        "reason": "Below threshold.",
        "errors": [],
    })
    response = backend.post("/api/stock/1/mcp-check")
    assert response.status_code == 200
    assert response.get_json()["result"]["recommended_order_quantity"] == 32


def test_mcp_stock_check_rejects_malformed_tool_output(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(mcp_client, "_execute", lambda _arguments: {"tool": "wrong"})
    response = backend.post("/api/stock/1/mcp-check")
    assert response.status_code == 502


def test_rag_ask_scopes_question_to_inventory(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    synced = []
    monkeypatch.setattr(rag_client, "ensure_synced", synced.append)
    monkeypatch.setattr(rag_client, "ask", lambda question: {
        "status": "ok", "answer": "The item is below threshold.",
        "sources": [], "confidence": "high",
    })
    response = backend.post("/api/stock/ask", json={
        "question": "Which Audio items are low?",
    })
    assert response.status_code == 200
    assert response.get_json()["question"] == "Which Audio items are low?"
    assert synced[0] == db_client.list_stock


def test_rag_ask_requires_a_valid_question(backend, fake_db):
    response = backend.post("/api/stock/ask", json={"question": "why?"})
    assert response.status_code == 400


def test_rag_stock_document_has_inventory_scope(fake_db):
    document = rag_client.stock_document(fake_db.get_stock(1))
    assert document["id"] == "inventory:stock:1"
    assert document["metadata"]["feature"] == "inventory_stock"
    assert "quantity is 18" in document["text"]


def test_rag_rejects_citations_from_another_feature():
    with pytest.raises(rag_client.RAGBadResponse):
        rag_client._validate_response({
            "status": "ok",
            "answer": "A grounded answer.",
            "confidence": "high",
            "sources": [{
                "source": "Product Catalogue",
                "section": "Listings",
                "snippet": "Catalogue facts.",
                "metadata": {"feature": "product_catalogue"},
            }],
        })


def test_rag_ask_rejects_non_object_response(monkeypatch):
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        rag_client,
        "_post",
        lambda *_args, **_kwargs: (SimpleNamespace(status_code=200), []),
    )
    with pytest.raises(rag_client.RAGBadResponse):
        rag_client.ask("Which stock items are low?")


# A partial update must change at least one recognised field.
def test_clean_stock_partial_requires_a_field():
    with pytest.raises(ValidationError):
        clean_stock({}, partial=True)