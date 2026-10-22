"""Student 5 sends the shared credential on review index mutations."""

from app import rag_client
from app.config import Config


def test_review_writes_and_deletes_send_service_token(monkeypatch):
    token = "test-rag-service-token"
    monkeypatch.setattr(Config, "RAG_SERVICE_TOKEN", token)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["headers"]))

    def delete(url, **kwargs):
        calls.append((url, kwargs["headers"]))

    monkeypatch.setattr(rag_client.requests, "post", post)
    monkeypatch.setattr(rag_client.requests, "delete", delete)
    review = {"review_id": 1, "review": "Great product.", "product_sku": "W-1", "rating": 5}

    rag_client.index_review(review)
    rag_client.remove_review(1)

    assert [headers for _, headers in calls] == [
        {"X-RAG-Service-Token": token}, {"X-RAG-Service-Token": token}
    ]
