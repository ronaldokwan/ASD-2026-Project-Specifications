from api_client import ApiError

import conftest

api = conftest.frontend_api

LISTING = {
    "tool": "check_product_listing",
    "server": "http://host.docker.internal:7002/mcp",
    "product_id": 1,
    "elapsed_ms": 9,
    "arguments": {
        "sku": "SKU-AUD-1001",
        "name": "Aurora Wireless Headphones",
        "category": "Audio",
        "price": 199.95,
        "status": "active",
    },
    "result": {
        "tool": "check_product_listing",
        "sku": "SKU-AUD-1001",
        "listing_status": "ready",
        "price_position": "within_range",
        "price_vs_average_pct": 33.3,
        "comparable_count": 2,
        "description_word_count": 12,
        "issues": [],
        "errors": [],
        "warnings": ["status is archived, so the product is hidden from shoppers"],
    },
}
GROUNDED = {
    "status": "ok",
    "question": "Which headphones cancel noise?",
    "answer": "Over-ear Bluetooth headphones with active noise cancelling.",
    "confidence": "medium",
    "sources": [
        {
            "source": "Product Catalogue database",
            "section": "SKU-AUD-1001 Aurora Wireless Headphones",
            "snippet": "Aurora Wireless Headphones (SKU-AUD-1001) is an active...",
        }
    ],
}


def test_page_offers_mcp_and_rag(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert 'id="mcp-panel"' in html
    assert 'hx-post="/catalogue/ask"' in html
    assert 'hx-post="/products/1/mcp-check"' in html  # Check button on each row


def test_mcp_check_renders_the_structured_result(frontend, fake_api, monkeypatch):
    calls = []
    monkeypatch.setattr(
        api,
        "check_listing",
        lambda pid: calls.append(pid) or LISTING,
    )
    html = frontend.post("/products/1/mcp-check").get_data(as_text=True)
    assert calls == [1]
    assert "Ready to publish" in html
    assert "within range" in html
    assert "+33.3%" in html
    assert "hidden from shoppers" in html
    assert "check_product_listing" in html


def test_mcp_outage_explains_how_to_start_the_server(frontend, fake_api, monkeypatch):
    def boom(pid):
        raise ApiError("MCP server unavailable", 503)

    monkeypatch.setattr(api, "check_listing", boom)
    html = frontend.post("/products/1/mcp-check").get_data(as_text=True)
    assert "MCP server unavailable" in html
    assert "run-ai-services.sh" in html


def test_rag_answer_shows_citations_and_confidence(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api, "ask_catalogue", lambda q: GROUNDED)
    html = frontend.post(
        "/catalogue/ask", data={"question": "Which headphones cancel noise?"}
    ).get_data(as_text=True)
    assert "active noise cancelling" in html
    assert 'id="rag-confidence">medium<' in html
    assert "SKU-AUD-1001 Aurora Wireless Headphones" in html
    assert "Product Catalogue database" in html


def test_rag_insufficient_context_is_its_own_state(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(
        api,
        "ask_catalogue",
        lambda q: {
            "status": "insufficient_context",
            "answer": "",
            "sources": [],
            "confidence": "insufficient",
            "question": q,
            "message": "Insufficient relevant context was found.",
        },
    )
    html = frontend.post(
        "/catalogue/ask", data={"question": "Who won the world cup?"}
    ).get_data(as_text=True)
    assert "Insufficient context." in html
    assert 'id="rag-answer"' not in html


def test_rag_short_question_never_reaches_the_backend(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(
        api,
        "ask_catalogue",
        lambda q: (_ for _ in ()).throw(AssertionError),
    )
    html = frontend.post("/catalogue/ask", data={"question": "hi"}).get_data(
        as_text=True
    )
    assert "at least 5 characters" in html


def test_rag_outage_is_reported(frontend, fake_api, monkeypatch):
    def boom(q):
        raise ApiError("RAG server unavailable", 503)

    monkeypatch.setattr(api, "ask_catalogue", boom)
    html = frontend.post(
        "/catalogue/ask", data={"question": "Which headphones cancel noise?"}
    ).get_data(as_text=True)
    assert "RAG server unavailable" in html
