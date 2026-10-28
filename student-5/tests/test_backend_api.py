"""Student 5 - backend/API microservice tests.

The database, catalogue and AI-Mode hops are stubbed, so these tests cover the
API contract, the validation rules and the AI request the backend builds.
"""

import json

import pytest

from app import ai_agent, db_client, mcp_client, multi_agent_client, rag_client
from app.config import Config
from app.validation import ValidationError, clean_review


# -------------------------------------------------------------------- health
def test_health_reports_the_feature(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "ai_mode_health", lambda: {"status": "ok"})
    body = backend.get("/health").get_json()
    assert body["student"] == 5
    assert body["feature"] == "Reviews and Ratings"
    assert body["status"] == "ok"


def test_products_endpoint_proxies_the_catalogue(backend, fake_catalogue):
    body = backend.get("/api/products").get_json()
    assert {p["sku"] for p in body["products"]} == {"SKU-AUD-1001", "SKU-HOM-3001"}


# ---------------------------------------------------------------------- READ
def test_list_reviews(backend, fake_db):
    body = backend.get("/api/reviews").get_json()
    assert body["count"] == 3


def test_list_reviews_filtered_by_product(backend, fake_db):
    body = backend.get("/api/reviews?product_sku=SKU-AUD-1001").get_json()
    assert body["count"] == 2


def test_get_one_review(backend, fake_db):
    assert backend.get("/api/reviews/r1").get_json()["product_sku"] == "SKU-AUD-1001"


def test_get_missing_review_returns_404(backend, fake_db):
    response = backend.get("/api/reviews/missing")
    assert response.status_code == 404
    assert "error" in response.get_json()


# -------------------------------------------------------------------- CREATE
def test_create_review(backend, fake_db):
    response = backend.post("/api/reviews", json={
        "product_sku": "sku-new-1", "user_id": "new-user", "rating": "4",
        "review": "Solid product overall.",
    })
    assert response.status_code == 201
    body = response.get_json()
    assert body["product_sku"] == "SKU-NEW-1"  # normalised to upper case
    assert body["rating"] == 4


@pytest.mark.parametrize("payload, expected_error", [
    ({"user_id": "u", "rating": 3, "review": "No SKU supplied here."}, "product_sku is required"),
    ({"product_sku": "SKU-1", "rating": 3, "review": "No user supplied here."}, "user_id is required"),
    ({"product_sku": "SKU-1", "user_id": "u", "review": "No rating supplied here."}, "rating is required"),
    ({"product_sku": "SKU-1", "user_id": "u", "rating": "abc", "review": "Bad rating type here."},
     "rating must be a whole number"),
    ({"product_sku": "SKU-1", "user_id": "u", "rating": 9, "review": "Rating out of range here."},
     "rating must be between"),
    ({"product_sku": "SKU-1", "user_id": "u", "rating": 3, "review": "hi"}, "review must be between"),
    ({"product_sku": "!!", "user_id": "u", "rating": 3, "review": "Bad sku format here."},
     "product_sku must be"),
])
def test_create_rejects_invalid_payloads(backend, fake_db, payload, expected_error):
    response = backend.post("/api/reviews", json=payload)
    assert response.status_code == 400
    assert any(expected_error in detail for detail in response.get_json()["details"])


# -------------------------------------------------------------- UPDATE/DELETE
def test_partial_update(backend, fake_db):
    body = backend.put("/api/reviews/r1", json={"rating": 1}).get_json()
    assert body["rating"] == 1
    assert body["product_sku"] == "SKU-AUD-1001"


def test_update_with_no_fields_is_rejected(backend, fake_db):
    assert backend.put("/api/reviews/r1", json={}).status_code == 400


def test_delete_review(backend, fake_db):
    assert backend.delete("/api/reviews/r1").get_json() == {"deleted": "r1"}
    assert backend.get("/api/reviews/r1").status_code == 404


def test_database_outage_returns_503(backend, monkeypatch):
    def boom(**_kwargs):
        raise db_client.DatabaseError("connection refused")

    monkeypatch.setattr(db_client, "list_reviews", boom)
    response = backend.get("/api/reviews")
    assert response.status_code == 503
    assert "database microservice unavailable" in response.get_json()["error"]


# ------------------------------------------------------------------- AI-mode
def test_ai_endpoint_returns_result_and_trace(backend, fake_db, fake_catalogue, monkeypatch):
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
                    "result": {
                        "summary": "Reviewers love the noise cancelling but some dislike the fit.",
                        "pros": "great noise cancelling; long battery life",
                        "cons": "headband can pinch",
                    },
                    "attempts": 1,
                    "fallback_used": False,
                    "model": "qwen2.5:0.5b",
                    "elapsed_ms": 900,
                    "trace": [{"step": "Plan"}, {"step": "Act"}, {"step": "Observe"}],
                }

        return Response()

    monkeypatch.setattr(ai_agent.requests, "post", fake_post)

    response = backend.post("/api/reviews/ai", json={"product_sku": "SKU-AUD-1001"})
    body = response.get_json()

    assert response.status_code == 200
    assert "noise cancelling" in body["result"]["summary"]
    assert [step["step"] for step in body["trace"]] == ["Plan", "Act", "Observe"]

    # The request must be grounded in real review facts (the Plan step) and
    # must declare the guardrails used by the Observe step.
    payload = captured["payload"]
    assert payload["context"]["review_count"] == 2
    assert payload["context"]["product_name"] == "Aurora Wireless Headphones"
    assert payload["output_schema"]["summary"]["max_words"] == 40
    assert payload["fallback"]["summary"]


def test_ai_endpoint_requires_product_sku(backend, fake_db):
    assert backend.post("/api/reviews/ai", json={"product_sku": "x"}).status_code == 400


def test_ai_service_outage_returns_503(backend, fake_db, fake_catalogue, monkeypatch):
    def boom(*_args, **_kwargs):
        raise ai_agent.requests.RequestException("connection refused")

    monkeypatch.setattr(ai_agent.requests, "post", boom)
    response = backend.post("/api/reviews/ai", json={"product_sku": "SKU-AUD-1001"})
    assert response.status_code == 503
    assert "AI-Mode" in response.get_json()["error"]


def test_ai_fallback_reflects_no_reviews(fake_db):
    context = ai_agent.build_context("SKU-DOES-NOT-EXIST")
    assert context["review_count"] == 0
    fallback = ai_agent._fallback(context)
    assert "no reviews" in fallback["summary"].lower()


def test_ai_fallback_is_grounded_in_the_rating_distribution(fake_db):
    # SKU-AUD-1001 has one 5-star and one 2-star review in fake_db.
    context = ai_agent.build_context("SKU-AUD-1001")
    fallback = ai_agent._fallback(context)
    assert "1 review(s) rated 4 or 5 stars" in fallback["pros"]
    assert "1 review(s) rated 1 or 2 stars" in fallback["cons"]


# --------------------------------------------------- Release 1: RAG and MCP
def test_create_review_indexes_it_in_the_shared_rag_corpus(backend, fake_db, fake_rag):
    backend.post("/api/reviews", json={
        "product_sku": "sku-new-1", "user_id": "new-user", "rating": "4",
        "review": "Solid product overall.",
    })
    indexed = list(fake_rag["indexed"].values())
    assert indexed and indexed[0]["review"] == "Solid product overall."


def test_delete_review_removes_it_from_the_shared_rag_corpus(backend, fake_db, fake_rag):
    backend.delete("/api/reviews/r1")
    assert "r1" in fake_rag["removed"]


def test_ask_returns_a_grounded_answer_with_validation(backend, fake_db, fake_rag, monkeypatch):
    monkeypatch.setattr(ai_agent, "validate_rag_answer", lambda **kwargs: {
        "ok": True, "result": {"grounded": "true", "unsupported_claims": "none",
                                "confidence_ok": "true", "notes": "matches the sources"},
    })
    fake_rag["indexed"]["r1"] = {"review_id": "r1", "product_sku": "SKU-AUD-1001",
                                  "review": "Fantastic noise cancelling."}

    response = backend.post("/api/reviews/ask", json={
        "product_sku": "SKU-AUD-1001", "question": "How is the noise cancelling?",
    })
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["sources"]
    assert body["validation"]["result"]["grounded"] == "true"


def test_ask_returns_insufficient_context_when_nothing_relevant(backend, fake_db, fake_rag):
    response = backend.post("/api/reviews/ask", json={
        "product_sku": "SKU-AUD-1001", "question": "Anything about this product?",
    })
    body = response.get_json()

    assert body["status"] == "insufficient_context"
    assert "validation" not in body  # nothing to validate without an answer


def test_ask_requires_a_product_and_a_real_question(backend, fake_db):
    assert backend.post("/api/reviews/ask", json={"product_sku": "x", "question": "ok?"}).status_code == 400
    assert backend.post("/api/reviews/ask", json={"product_sku": "SKU-1", "question": "hi"}).status_code == 400


def test_moderate_runs_the_tool_and_validates_it(backend, fake_db, fake_mcp, monkeypatch):
    monkeypatch.setattr(ai_agent, "validate_mcp_result", lambda **kwargs: {
        "ok": True, "result": {"valid": "true", "notes": "matches the review", "confidence": "high"},
    })

    response = backend.post("/api/reviews/moderate", json={
        "product_sku": "SKU-AUD-1001", "review_text": "Great sound and battery life.", "rating": 5,
    })
    body = response.get_json()

    assert response.status_code == 200
    assert body["tool_result"]["flagged"] is False
    assert body["validation"]["result"]["valid"] == "true"


def test_moderate_flags_spammy_reviews(backend, fake_db, fake_mcp, monkeypatch):
    monkeypatch.setattr(ai_agent, "validate_mcp_result", lambda **kwargs: {
        "ok": True, "result": {"valid": "true", "notes": "correctly flagged", "confidence": "high"},
    })
    response = backend.post("/api/reviews/moderate", json={
        "product_sku": "SKU-AUD-1001", "review_text": "buy now at http://spam.example", "rating": 5,
    })
    assert response.get_json()["tool_result"]["flagged"] is True


def test_moderate_requires_product_and_review_text(backend, fake_db):
    assert backend.post("/api/reviews/moderate",
                         json={"product_sku": "x", "review_text": "ok"}).status_code == 400
    assert backend.post("/api/reviews/moderate",
                         json={"product_sku": "SKU-1", "review_text": ""}).status_code == 400


def test_mcp_service_outage_returns_503(backend, fake_db, monkeypatch):
    def boom(**_kwargs):
        raise mcp_client.MCPServiceUnavailable("connection refused")

    monkeypatch.setattr(mcp_client, "check_review_quality", boom)
    response = backend.post("/api/reviews/moderate", json={
        "product_sku": "SKU-AUD-1001", "review_text": "Great product.", "rating": 5,
    })
    assert response.status_code == 503
    assert "MCP" in response.get_json()["error"]


def test_rag_service_outage_returns_503(backend, fake_db, monkeypatch):
    def boom(*_args, **_kwargs):
        raise rag_client.RAGServiceError("connection refused")

    monkeypatch.setattr(rag_client, "ask", boom)
    response = backend.post("/api/reviews/ask", json={
        "product_sku": "SKU-AUD-1001", "question": "How is it?",
    })
    assert response.status_code == 503
    assert "RAG" in response.get_json()["error"]


# --------------------------------------------------- Release 2: Multi-Agent
def test_multi_agent_start_builds_review_and_moderation_evidence(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    monkeypatch.setattr(mcp_client, "check_review_quality", lambda **_kwargs: {
        "tool": "check_review_quality",
        "result": {
            "flagged": False, "reasons": ["no issues found"],
            "spam_score": 0.0, "duplicate_risk": "low", "word_count": 4,
        },
    })
    captured = {}

    def start(method, path, **kwargs):
        captured.update(kwargs["json"])
        return {"workflow_id": "workflow-123", "status": "queued"}

    monkeypatch.setattr(multi_agent_client, "_call", start)
    response = backend.post("/api/reviews/r1/multi-agent")
    assert response.status_code == 202
    assert response.get_json()["workflow_id"] == "workflow-123"
    assert captured["subject_ref"] == "student-5-review:r1"
    assert {item["id"] for item in captured["evidence"]} == {"review_facts", "mcp_moderation"}
    facts = json.loads(next(
        item["content"] for item in captured["evidence"] if item["id"] == "review_facts"
    ))
    assert facts["review_id"] == "r1"
    assert facts["review_text"] == "Fantastic noise cancelling."
    assert facts["existing_review_count"] == 2  # r1 and r2 share SKU-AUD-1001
    assert captured["request"]["worker_evidence_ids"] == ["review_facts", "mcp_moderation"]
    assert "worker_policy_evidence_ids" not in captured["request"]


def test_multi_agent_start_marks_moderation_unavailable_on_outage(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)

    def boom(**_kwargs):
        raise mcp_client.MCPServiceUnavailable("connection refused")

    monkeypatch.setattr(mcp_client, "check_review_quality", boom)
    captured = {}

    def start(_method, _path, **kwargs):
        captured.update(kwargs["json"])
        return {"workflow_id": "workflow-456", "status": "queued"}

    monkeypatch.setattr(multi_agent_client, "_call", start)
    response = backend.post("/api/reviews/r1/multi-agent")
    assert response.status_code == 202
    moderation = next(item for item in captured["evidence"] if item["id"] == "mcp_moderation")
    assert moderation["status"] == "unavailable"


def test_multi_agent_disabled_returns_503(backend, fake_db):
    response = backend.post("/api/reviews/r1/multi-agent")
    assert response.status_code == 503
    assert response.get_json()["error"] == "Multi-Agent workflow unavailable"


def test_multi_agent_unknown_review_is_404(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    response = backend.post("/api/reviews/does-not-exist/multi-agent")
    assert response.status_code == 404


def test_multi_agent_routes_check_review_ownership_and_record_decisions(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    subject_ref = "student-5-review:r1"
    calls = []

    def call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path == "/workflow/history":
            return {"count": 1, "workflows": [{"workflow_id": "workflow-123"}]}
        if method == "GET":
            return {"workflow_id": "workflow-123", "subject_ref": subject_ref, "status": "human_review"}
        return {"workflow_id": "workflow-123", "subject_ref": subject_ref,
                "status": "accepted", "human_decision": kwargs["json"]}

    monkeypatch.setattr(multi_agent_client, "_call", call)
    history = backend.get("/api/reviews/r1/multi-agent/history")
    assert history.status_code == 200 and history.get_json()["count"] == 1
    status = backend.get("/api/reviews/r1/multi-agent/workflow-123")
    assert status.get_json()["status"] == "human_review"
    review = backend.post("/api/reviews/r1/multi-agent/workflow-123/review", json={
        "decision": "accept", "feedback": "Looks fine.",
    })
    assert review.status_code == 200
    assert review.get_json()["status"] == "accepted"
    assert [item[1] for item in calls] == [
        "/workflow/history", "/workflow/workflow-123", "/workflow/workflow-123",
        "/workflow/workflow-123/review",
    ]


def test_multi_agent_review_rejects_a_workflow_belonging_to_another_review(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    monkeypatch.setattr(multi_agent_client, "_call", lambda _method, _path, **_kwargs: {
        "workflow_id": "workflow-999", "subject_ref": "student-5-review:r2", "status": "human_review",
    })
    response = backend.post("/api/reviews/r1/multi-agent/workflow-999/review", json={"decision": "accept"})
    assert response.status_code == 502


# ------------------------------------------------------------- validation unit
def test_clean_review_normalises_values():
    cleaned = clean_review({
        "product_sku": " sku-abc ", "user_id": "user_1", "rating": "4",
        "review": "  Great product, would buy again.  ",
    })
    assert cleaned["product_sku"] == "SKU-ABC"
    assert cleaned["rating"] == 4
    assert cleaned["review"] == "Great product, would buy again."


def test_clean_review_partial_requires_a_field():
    with pytest.raises(ValidationError):
        clean_review({}, partial=True)
