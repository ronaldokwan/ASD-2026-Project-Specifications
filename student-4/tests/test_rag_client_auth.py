"""Student 4 sends the shared credential on RAG index mutations."""

from app import rag_client
from app.config import Config


class Response:
    status_code = 200

    @staticmethod
    def json():
        return {"ok": True, "documents_indexed": 1, "chunks_indexed": 1}


def test_stock_writes_and_deletes_send_service_token(monkeypatch):
    token = "test-rag-service-token"
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(Config, "RAG_SERVICE_TOKEN", token)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["headers"]))
        return Response()

    def delete(url, **kwargs):
        calls.append((url, kwargs["headers"]))
        return Response()

    monkeypatch.setattr(rag_client.requests, "post", post)
    monkeypatch.setattr(rag_client.requests, "delete", delete)
    stock = {
        "id": 1, "name": "Widget", "sku": "W-1", "category": "Audio",
        "quantity": 3, "restock_threshold": 5, "location": "A1",
    }

    rag_client.sync_stock(stock)
    rag_client.remove_stock(1)

    assert [headers for _, headers in calls] == [
        {"X-RAG-Service-Token": token}, {"X-RAG-Service-Token": token}
    ]
