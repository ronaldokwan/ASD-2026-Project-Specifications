import importlib.util
import os

import pytest

from app import ai_agent, mcp_client, rag_client
from app.config import Config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "shared_mcp_tools", os.path.join(REPO_ROOT, "ai-services", "mcp-server", "tools.py")
)
shared_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared_tools)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.content = b"{}"

    def json(self):
        return self._body


@pytest.fixture()
def mcp_on(monkeypatch, fake_db):
    """MCP enabled, with the transport replaced by the real shared tool."""
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    fake_db.rows[3] = {
        "id": 3,
        "sku": "SKU-AUD-1002",
        "name": "Pebble Bluetooth Speaker",
        "description": "Pocket-sized waterproof speaker.",
        "category": "Audio",
        "price": 59.00,
        "status": "active",
        "created_at": "2026-08-01 09:00:00",
        "updated_at": "2026-08-01 09:00:00",
    }
    calls = []

    def execute(arguments):
        calls.append(arguments)
        return shared_tools.check_product_listing(**arguments)

    monkeypatch.setattr(mcp_client, "_execute", execute)
    return calls


@pytest.fixture()
def rag_server(monkeypatch):
    """RAG enabled, with an in-memory stand-in for the shared RAG server."""
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    state = {
        "documents": {},
        "deleted": [],
        "queries": [],
        "answer": None,
        "fail": False,
    }

    def post(url, json=None, timeout=None):
        if state["fail"]:
            raise rag_client.requests.ConnectionError("connection refused")
        if url.endswith("/rag/documents"):
            for doc in json["documents"]:
                state["documents"][doc["id"]] = doc
            return FakeResponse(
                {
                    "ok": True,
                    "documents_indexed": len(json["documents"]),
                    "chunks_indexed": len(json["documents"]),
                }
            )
        if url.endswith("/rag/query"):
            state["queries"].append(json)
            return FakeResponse(
                state["answer"],
                503 if state["answer"].get("status") == "service_unavailable" else 200,
            )
        raise AssertionError("unexpected RAG url " + url)

    def delete(url, timeout=None):
        state["deleted"].append(url.rsplit("/", 1)[-1])
        return FakeResponse({"ok": True, "chunks_removed": 1})

    monkeypatch.setattr(rag_client.requests, "post", post)
    monkeypatch.setattr(rag_client.requests, "delete", delete)
    return state


GROUNDED = {
    "status": "ok",
    "answer": "Aurora Wireless Headphones (SKU-AUD-1001) is an active Audio product "
    "priced at 199.95 AUD.",
    "sources": [
        {
            "doc_id": "catalogue:product:1",
            "chunk_id": "catalogue:product:1::0",
            "source": "Product Catalogue database",
            "section": "SKU-AUD-1001 Aurora Wireless Headphones",
            "snippet": "Aurora Wireless Headphones (SKU-AUD-1001) is an active Audio product "
            "priced at 199.95 AUD. Over-ear headphones.",
            "text": "Aurora Wireless Headphones (SKU-AUD-1001) is an active Audio product "
            "priced at 199.95 AUD. Over-ear headphones. Full chunk beyond the preview.",
            "metadata": {"feature": "product_catalogue", "product_sku": "SKU-AUD-1001"},
        }
    ],
    "confidence": "medium",
    "retrieved_count": 1,
}
INSUFFICIENT = {
    "status": "insufficient_context",
    "answer": "",
    "confidence": "insufficient",
    "sources": [],
    "message": "Insufficient relevant context was found.",
}


# ------------------------------------------------------------------------ MCP
def test_mcp_check_grounds_the_tool_with_comparables(backend, mcp_on):
    response = backend.post("/api/products/1/mcp-check", json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "check_product_listing"
    assert body["server"].endswith("/mcp")
    # Grounding excludes the product itself: only the speaker is comparable.
    assert mcp_on[0]["comparable_count"] == 1
    assert mcp_on[0]["comparable_avg_price"] == 59.0
    assert body["result"]["listing_status"] == "needs_attention"  # 2-word description
    assert body["result"]["price_position"] == "above_range"


def test_mcp_check_with_no_comparables(backend, fake_db, mcp_on):
    body = backend.post("/api/products/2/mcp-check", json={}).get_json()
    assert mcp_on[0]["comparable_count"] == 0
    assert "comparable_avg_price" not in mcp_on[0]
    assert body["result"]["price_position"] == "no_comparables"


def test_mcp_check_unknown_product_is_404(backend, mcp_on):
    assert backend.post("/api/products/404/mcp-check", json={}).status_code == 404
    assert mcp_on == []


def test_mcp_disabled_returns_503(backend, fake_db):
    response = backend.post("/api/products/1/mcp-check", json={})
    assert response.status_code == 503
    assert response.get_json()["error"] == "MCP server unavailable"


def test_mcp_unreachable_returns_503(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(Config, "MCP_SERVER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(Config, "MCP_TIMEOUT", 3)
    response = backend.post("/api/products/1/mcp-check", json={})
    assert response.status_code == 503
    assert "unreachable" in response.get_json()["detail"]


@pytest.mark.parametrize(
    "bad_result",
    [
        None,
        {"tool": "check_customer_profile"},
        dict(
            shared_tools.check_product_listing("SKU-1", "Ab", "Audio", 10, "active"),
            listing_status="maybe",
        ),
        dict(
            shared_tools.check_product_listing("SKU-1", "Ab", "Audio", 10, "active"),
            warnings="not a list",
        ),
    ],
)
def test_mcp_malformed_results_are_rejected(backend, fake_db, monkeypatch, bad_result):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(mcp_client, "_execute", lambda arguments: bad_result)
    response = backend.post("/api/products/1/mcp-check", json={})
    assert response.status_code == 502


# ------------------------------------------------------------------------ RAG
def test_product_document_is_short_citable_and_scoped():
    doc = rag_client.product_document(
        {
            "id": 7,
            "sku": "SKU-WEA-4001",
            "name": "Stride Watch",
            "category": "Wearables",
            "price": 249,
            "status": "archived",
            "description": "GPS running watch.",
        }
    )
    assert doc["id"] == "catalogue:product:7"
    assert doc["text"] == (
        "Stride Watch (SKU-WEA-4001) is an archived Wearables product "
        "priced at 249.00 AUD. GPS running watch."
    )
    assert doc["metadata"]["feature"] == "product_catalogue"
    assert doc["metadata"]["section"] == "SKU-WEA-4001 Stride Watch"


def test_ask_returns_a_grounded_answer_with_citations(backend, fake_db, rag_server):
    rag_server["answer"] = GROUNDED
    response = backend.post(
        "/api/catalogue/ask", json={"question": "Tell me about Aurora"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["confidence"] == "medium"
    assert body["sources"][0]["section"] == "SKU-AUD-1001 Aurora Wireless Headphones"
    # The query is scoped to this feature's sources only.
    assert rag_server["queries"][0]["filters"] == {"feature": "product_catalogue"}
    # The first question indexes the live catalogue into the shared corpus.
    assert set(rag_server["documents"]) == {
        "catalogue:product:1",
        "catalogue:product:2",
    }


def test_ask_reports_insufficient_context(backend, fake_db, rag_server):
    rag_server["answer"] = INSUFFICIENT
    body = backend.post(
        "/api/catalogue/ask",
        json={"question": "Who won the football world cup?"},
    ).get_json()
    assert body["status"] == "insufficient_context"
    assert body["answer"] == "" and body["sources"] == []
    assert body["confidence"] == "insufficient"


@pytest.mark.parametrize(
    "answer",
    [
        dict(INSUFFICIENT, answer="made up"),
        dict(GROUNDED, sources=[]),
        dict(GROUNDED, confidence="certain"),
        dict(
            GROUNDED,
            sources=[
                dict(GROUNDED["sources"][0], metadata={"feature": "customer_accounts"})
            ],
        ),
        {"status": "weird"},
    ],
)
def test_ask_rejects_ungrounded_or_foreign_answers(
    backend, fake_db, rag_server, answer
):
    rag_server["answer"] = answer
    response = backend.post(
        "/api/catalogue/ask", json={"question": "Tell me about Aurora"}
    )
    assert response.status_code == 502


def test_ask_model_unavailable_is_503(backend, fake_db, rag_server):
    rag_server["answer"] = {"status": "service_unavailable", "message": "model down"}
    response = backend.post(
        "/api/catalogue/ask", json={"question": "Tell me about Aurora"}
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "hi"},
        {"question": "x" * 501},
        {"question": 42},
        {},
    ],
)
def test_ask_validates_the_question(backend, fake_db, rag_server, payload):
    assert backend.post("/api/catalogue/ask", json=payload).status_code == 400
    assert rag_server["queries"] == []


def test_ask_disabled_returns_503(backend, fake_db):
    response = backend.post(
        "/api/catalogue/ask", json={"question": "Tell me about Aurora"}
    )
    assert response.status_code == 503
    assert response.get_json()["error"] == "RAG server unavailable"


def test_rag_sync_reindexes_every_product(backend, fake_db, rag_server):
    body = backend.post("/api/catalogue/rag-sync").get_json()
    assert body["documents_indexed"] == 2


def test_crud_keeps_the_rag_corpus_in_step(backend, fake_db, rag_server):
    created = backend.post(
        "/api/products",
        json={"name": "Cadence Earbuds", "category": "Audio", "price": 89.95},
    ).get_json()
    assert "catalogue:product:{}".format(created["id"]) in rag_server["documents"]

    backend.put("/api/products/1", json={"price": 149.95})
    assert "149.95 AUD" in rag_server["documents"]["catalogue:product:1"]["text"]

    backend.delete("/api/products/1")
    assert rag_server["deleted"] == ["catalogue:product:1"]


def test_rag_outage_never_blocks_a_catalogue_write(backend, fake_db, rag_server):
    rag_server["fail"] = True
    response = backend.post(
        "/api/products",
        json={"name": "Cadence Earbuds", "category": "Audio", "price": 89.95},
    )
    assert response.status_code == 201


# ------------------------------------------------- disabled-in-CI behaviour
def test_health_reports_disabled_integrations(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "AI_MODE_ENABLED", False)
    body = backend.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["ai_mode"] == {"status": "disabled"}
    assert body["mcp_server"] == {"status": "disabled"}
    assert body["rag_server"] == {"status": "disabled"}


def test_ai_copy_uses_the_fallback_without_a_network_call_when_disabled(
    backend, fake_db, monkeypatch
):
    monkeypatch.setattr(Config, "AI_MODE_ENABLED", False)
    monkeypatch.setattr(
        ai_agent.requests,
        "post",
        lambda *a, **k: pytest.fail("AI-Mode was called while disabled"),
    )
    response = backend.post(
        "/api/products/ai", json={"name": "Cadence", "category": "Audio"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["fallback_used"] is True
    assert body["result"]["price"] == 199.95  # grounded in the Audio average
