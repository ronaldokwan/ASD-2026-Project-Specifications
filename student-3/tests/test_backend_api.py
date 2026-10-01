"""Business API, validation, database-client, AI, MCP and RAG tests."""

import asyncio
import copy

import pytest

from app import ai_agent, db_client, mcp_client, rag_client
from app.config import Config
from app.validation import ValidationError, clean_customer


def customer_payload(**overrides):
    payload = {"name": "Taylor Example", "email": "taylor@example.test",
               "phone": "0400 123 456", "address": "Sydney NSW",
               "loyalty_tier": "Silver", "joined_at": "2025-05-01"}
    payload.update(overrides)
    return payload


def test_health_and_list_customers(backend, fake_db, monkeypatch):
    monkeypatch.setattr(ai_agent, "ai_mode_health", lambda: {"status": "ok"})
    assert backend.get("/health").get_json()["status"] == "ok"
    body = backend.get("/api/customers").get_json()
    assert body["count"] == 2


def test_search_by_name_and_email(backend, fake_db):
    assert backend.get("/api/customers?search=avery").get_json()["count"] == 1
    assert backend.get("/api/customers?search=jordan@example").get_json()["count"] == 1


def test_create_read_update_delete(backend, fake_db):
    created = backend.post("/api/customers", json=customer_payload())
    assert created.status_code == 201
    customer_id = created.get_json()["id"]
    assert backend.get("/api/customers/{}".format(customer_id)).status_code == 200
    assert backend.put("/api/customers/{}".format(customer_id),
                       json={"loyalty_tier": "Gold"}).get_json()["loyalty_tier"] == "Gold"
    assert backend.delete("/api/customers/{}".format(customer_id)).status_code == 200
    assert backend.get("/api/customers/{}".format(customer_id)).status_code == 404


@pytest.mark.parametrize("payload, message", [
    ({"email": "x@example.test"}, "name is required"),
    ({"name": "No Email"}, "email is required"),
    (customer_payload(email="not-an-email"), "valid email"),
    (customer_payload(loyalty_tier="Platinum"), "loyalty_tier"),
    (customer_payload(joined_at="03/09/2026"), "ISO date"),
])
def test_invalid_customer_payloads(backend, fake_db, payload, message):
    response = backend.post("/api/customers", json=payload)
    assert response.status_code == 400
    assert any(message in detail for detail in response.get_json()["details"])


def test_duplicate_email(backend, fake_db):
    response = backend.post("/api/customers", json=customer_payload(email="AVERY@example.test"))
    assert response.status_code == 409


def test_missing_customer(backend, fake_db):
    assert backend.get("/api/customers/999").status_code == 404


def test_database_failure_is_cleanly_reported(backend, monkeypatch):
    monkeypatch.setattr(db_client, "list_customers",
                        lambda **kwargs: (_ for _ in ()).throw(db_client.DatabaseError("offline")))
    assert backend.get("/api/customers").status_code == 503


def test_validation_unit_normalises_values():
    cleaned = clean_customer(customer_payload(
        email=" TAYLOR@EXAMPLE.TEST ", loyalty_tier="gold"
    ))
    assert cleaned["email"] == "taylor@example.test"
    assert cleaned["loyalty_tier"] == "Gold"


def test_partial_update_requires_a_field():
    with pytest.raises(ValidationError):
        clean_customer({}, partial=True)


def test_ai_reward_uses_stored_customer_and_grounding(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "AI_MODE_ENABLED", True)
    captured = {}

    class Response:
        content = b"{}"
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "result": {
                    "reward": "10% off the next purchase",
                    "reason": "This reward recognises a returning Silver-tier customer.",
                },
                "attempts": 1,
                "fallback_used": False,
                "model": "stub",
                "elapsed_ms": 1,
                "trace": [{"step": "Plan", "detail": "grounded"}],
            }

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return Response()

    monkeypatch.setattr(ai_agent.requests, "post", fake_post)
    body = backend.post("/api/customers/1/ai-reward").get_json()
    assert body["result"]["reward"] == "10% off the next purchase"
    assert body["grounding"] == {
        "customer_name": "Avery Brooks",
        "loyalty_tier": "Silver",
        "joined_at": "2025-01-10",
    }
    assert captured["payload"]["output_schema"]["reward"]["type"] == "string"
    assert "Ten percent off the next purchase" in captured["payload"]["task"]
    assert "copy this grounded sentence exactly" in captured["payload"]["task"]
    assert "Do not add or imply any purchase" in captured["payload"]["task"]


def test_ai_transport_failure_returns_tier_fallback(backend, fake_db, monkeypatch):
    monkeypatch.setattr(Config, "AI_MODE_ENABLED", True)
    monkeypatch.setattr(
        ai_agent.requests, "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ai_agent.requests.RequestException("connection refused"))
    )
    response = backend.post("/api/customers/1/ai-reward")
    body = response.get_json()
    assert response.status_code == 200
    assert body["fallback_used"] is True
    assert body["result"]["reward"] == "10% off the next purchase"
    assert body["trace"][0]["status"] == "fallback"


def profile_result(**overrides):
    result = {
        "tool": "check_customer_profile",
        "tier_valid": True,
        "membership_days": 629,
        "profile_status": "complete",
        "missing_optional_fields": [],
        "warnings": [],
        "errors": [],
    }
    result.update(overrides)
    return result


def test_mcp_profile_endpoint_returns_structured_result(backend, fake_db, monkeypatch):
    captured = {}

    def check(customer):
        captured["customer"] = customer
        return profile_result()

    monkeypatch.setattr(mcp_client, "check_customer_profile", check)
    response = backend.post("/api/customers/1/mcp-profile")
    assert response.status_code == 200
    assert response.get_json()["profile_status"] == "complete"
    assert captured["customer"]["loyalty_tier"] == "Silver"


def test_mcp_client_sends_only_privacy_minimised_grounding(monkeypatch):
    captured = {}
    monkeypatch.setattr(Config, "MCP_ENABLED", True)

    def execute(arguments):
        captured.update(arguments)
        return profile_result()

    monkeypatch.setattr(mcp_client, "_execute", execute)
    customer = {
        "id": 7, "name": "Private Name", "email": "private@example.test",
        "phone": "0400 111 222", "address": "Private address",
        "loyalty_tier": "Gold", "joined_at": "2024-08-19",
    }
    result = mcp_client.check_customer_profile(customer, as_of_date="2026-10-01")
    assert result["tool"] == "check_customer_profile"
    assert captured == {
        "loyalty_tier": "Gold", "joined_at": "2024-08-19",
        "has_phone": True, "has_address": True, "as_of_date": "2026-10-01",
    }
    assert not {"id", "name", "email", "phone", "address"}.intersection(captured)


def test_mcp_customer_not_found(backend, fake_db):
    assert backend.post("/api/customers/999/mcp-profile").status_code == 404


def test_mcp_timeout_is_reported_as_unavailable(monkeypatch):
    async def slow_call(_arguments):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(mcp_client, "_call_tool", slow_call)
    monkeypatch.setattr(Config, "MCP_TIMEOUT", 0.001)
    with pytest.raises(mcp_client.MCPServiceUnavailable, match="timed out"):
        mcp_client._execute({})


def test_mcp_unavailable_and_malformed_map_to_503_and_502(backend, fake_db, monkeypatch):
    monkeypatch.setattr(
        mcp_client, "check_customer_profile",
        lambda _customer: (_ for _ in ()).throw(
            mcp_client.MCPServiceUnavailable("offline")
        ),
    )
    assert backend.post("/api/customers/1/mcp-profile").status_code == 503

    monkeypatch.setattr(
        mcp_client, "check_customer_profile",
        lambda _customer: (_ for _ in ()).throw(
            mcp_client.MCPBadResponse("missing fields")
        ),
    )
    assert backend.post("/api/customers/1/mcp-profile").status_code == 502


def test_mcp_client_rejects_malformed_response(monkeypatch):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(mcp_client, "_execute", lambda _arguments: {"tool": "wrong"})
    with pytest.raises(mcp_client.MCPBadResponse):
        mcp_client.check_customer_profile({
            "loyalty_tier": "Gold", "joined_at": "2024-08-19",
            "phone": None, "address": None,
        })


def test_rag_endpoint_returns_grounded_answer_and_enforces_feature_filter(
    backend, monkeypatch
):
    captured = {}

    def fake_ask(question):
        captured["question"] = question
        return {
            "status": "ok", "answer": "Gold customers receive approved benefits.",
            "sources": [{"source": "customer-loyalty-policy.md",
                         "section": "Gold Membership", "snippet": "Gold benefits..."}],
            "confidence": "high",
        }

    monkeypatch.setattr(rag_client, "ask_loyalty_benefits", fake_ask)
    response = backend.post(
        "/api/loyalty-benefits/ask",
        json={"question": "What benefits are available to Gold customers?",
              "filters": {"feature": "reviews"}},
    )
    assert response.status_code == 200
    assert response.get_json()["confidence"] == "high"
    assert captured["question"] == "What benefits are available to Gold customers?"


def test_rag_client_always_sends_customer_accounts_filter(monkeypatch):
    captured = {}
    monkeypatch.setattr(Config, "RAG_ENABLED", True)

    class Response:
        status_code = 200

        def json(self):
            return {
                "status": "ok", "answer": "Gold benefit answer.", "confidence": "medium",
                "sources": [{"source": "customer-loyalty-policy.md",
                             "section": "Gold Membership", "snippet": "Gold benefit text."}],
            }

    def post(url, json=None, timeout=None):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(rag_client.requests, "post", post)
    rag_client.ask_loyalty_benefits("What are Gold benefits?")
    assert captured["json"]["filters"] == {"feature": "customer_accounts"}


def test_rag_insufficient_context_passes_through(backend, monkeypatch):
    monkeypatch.setattr(rag_client, "ask_loyalty_benefits", lambda _question: {
        "status": "insufficient_context", "answer": "", "sources": [],
        "confidence": "insufficient", "message": "Insufficient relevant context was found.",
    })
    body = backend.post(
        "/api/loyalty-benefits/ask", json={"question": "How do I reset a password?"}
    ).get_json()
    assert body["status"] == "insufficient_context"
    assert body["sources"] == []


def test_rag_timeout_and_unavailable_are_reported(monkeypatch):
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        rag_client.requests, "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(rag_client.requests.Timeout()),
    )
    with pytest.raises(rag_client.RAGServiceUnavailable, match="timed out"):
        rag_client.ask_loyalty_benefits("What are Gold benefits?")

    monkeypatch.setattr(
        rag_client.requests, "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            rag_client.requests.ConnectionError("offline")
        ),
    )
    with pytest.raises(rag_client.RAGServiceUnavailable, match="unreachable"):
        rag_client.ask_loyalty_benefits("What are Gold benefits?")


def test_rag_client_rejects_malformed_response(monkeypatch):
    monkeypatch.setattr(Config, "RAG_ENABLED", True)

    class Response:
        status_code = 200

        def json(self):
            return {"status": "ok", "answer": "Unsupported", "sources": []}

    monkeypatch.setattr(rag_client.requests, "post", lambda *args, **kwargs: Response())
    with pytest.raises(rag_client.RAGBadResponse):
        rag_client.ask_loyalty_benefits("What are Gold benefits?")


def test_mcp_and_rag_do_not_mutate_customer_database(backend, fake_db, monkeypatch):
    before = copy.deepcopy(fake_db.rows)
    monkeypatch.setattr(mcp_client, "check_customer_profile", lambda _customer: profile_result())
    monkeypatch.setattr(rag_client, "ask_loyalty_benefits", lambda _question: {
        "status": "insufficient_context", "answer": "", "sources": [],
        "confidence": "insufficient", "message": "Insufficient relevant context was found.",
    })
    backend.post("/api/customers/1/mcp-profile")
    backend.post("/api/loyalty-benefits/ask", json={"question": "Unknown policy question"})
    assert fake_db.rows == before
