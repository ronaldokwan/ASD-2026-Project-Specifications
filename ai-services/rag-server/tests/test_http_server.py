"""HTTP-layer tests for the shared RAG server's Flask front door.

The pipeline itself is monkeypatched here (it has its own dedicated tests in
test_rag_pipeline.py) so this file only checks routing, validation and
status codes.

Run from the repository root: pytest ai-services/rag-server/tests -v
"""

import os
import sys

import pytest

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

import http_server  # noqa: E402

TEST_AUTH_VALUE = "test-rag-service-token"
AUTH_HEADERS = {http_server.AUTH_HEADER: TEST_AUTH_VALUE}


def client():
    http_server.app.config.update(TESTING=True)
    return http_server.app.test_client()


def test_health():
    res = client().get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_add_documents_requires_id_and_text(monkeypatch):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    res = client().post(
        "/rag/documents", json={"documents": [{"id": "r1"}]}, headers=AUTH_HEADERS
    )
    assert res.status_code == 400


@pytest.mark.parametrize("headers", [{}, {http_server.AUTH_HEADER: "wrong"}])
def test_add_documents_rejects_missing_or_wrong_credential(monkeypatch, headers):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    monkeypatch.setattr(
        http_server,
        "upsert_documents",
        lambda _docs: pytest.fail("write reached pipeline"),
    )
    res = client().post(
        "/rag/documents",
        json={"documents": [{"id": "r1", "text": "hello"}]},
        headers=headers,
    )
    assert res.status_code == 401
    assert "credential" in res.get_json()["error"]


def test_add_documents_calls_pipeline(monkeypatch):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    calls = {}

    def fake_upsert(docs):
        calls["docs"] = docs
        return {"ok": True, "documents_indexed": 1}

    monkeypatch.setattr(http_server, "upsert_documents", fake_upsert)

    res = client().post(
        "/rag/documents", json={"documents": [{"id": "r1", "text": "hello"}]},
        headers=AUTH_HEADERS,
    )
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert calls["docs"][0]["id"] == "r1"


@pytest.mark.parametrize("headers", [{}, {http_server.AUTH_HEADER: "wrong"}])
def test_delete_rejects_missing_or_wrong_credential(monkeypatch, headers):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    monkeypatch.setattr(
        http_server,
        "delete_document",
        lambda _doc_id: pytest.fail("delete reached pipeline"),
    )
    res = client().delete("/rag/documents/r1", headers=headers)
    assert res.status_code == 401
    assert "credential" in res.get_json()["error"]


def test_delete_document(monkeypatch):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    monkeypatch.setattr(
        http_server,
        "delete_document",
        lambda doc_id: {"ok": True, "chunks_removed": 1},
    )
    res = client().delete("/rag/documents/r1", headers=AUTH_HEADERS)
    assert res.status_code == 200
    assert res.get_json()["chunks_removed"] == 1


def test_document_writes_fail_closed_when_service_token_is_unset(monkeypatch):
    monkeypatch.delenv("RAG_SERVICE_TOKEN", raising=False)
    res = client().post(
        "/rag/documents",
        json={"documents": [{"id": "r1", "text": "hello"}]},
        headers=AUTH_HEADERS,
    )
    assert res.status_code == 401


def test_query_requires_a_question():
    res = client().post("/rag/query", json={})
    assert res.status_code == 400


def test_query_returns_insufficient_context(monkeypatch):
    monkeypatch.setattr(http_server, "answer_question", lambda q, top_k=5, filters=None: {
        "status": "insufficient_context", "confidence": "insufficient", "sources": [],
        "message": "Not enough relevant context was found to answer this question.",
    })
    res = client().post("/rag/query", json={"query": "unrelated question"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "insufficient_context"


def test_query_returns_grounded_answer(monkeypatch):
    monkeypatch.setattr(http_server, "answer_question", lambda q, top_k=5, filters=None: {
        "status": "ok", "answer": "Reviewers like the battery life.",
        "sources": [{"doc_id": "r1", "chunk_id": "r1::0", "snippet": "...", "metadata": {}}],
        "confidence": "high", "retrieved_count": 1,
    })
    res = client().post(
        "/rag/query",
        json={"query": "How is the battery?", "filters": {"product_sku": "SKU-1"}},
    )
    body = res.get_json()
    assert res.status_code == 200
    assert body["confidence"] == "high"
    assert body["sources"]


def test_query_rejects_invalid_top_k():
    res = client().post("/rag/query", json={"query": "valid question", "top_k": "many"})
    assert res.status_code == 400


def test_query_returns_503_when_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(http_server, "answer_question", lambda q, top_k=5, filters=None: {
        "status": "service_unavailable", "answer": "", "sources": [],
        "confidence": "unavailable", "message": "The local language model is unavailable.",
    })
    res = client().post("/rag/query", json={"query": "What are Gold benefits?"})
    assert res.status_code == 503
    assert res.get_json()["status"] == "service_unavailable"
