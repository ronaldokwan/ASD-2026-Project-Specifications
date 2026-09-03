"""Business API, validation, database-client, and AI tests."""

import pytest

from app import ai_agent, db_client
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
