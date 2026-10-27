"""Release 2: backend/API integration with the shared Multi-Agent server.

The Multi-Agent server, MCP transport and RAG server are all stubbed, so these
run in CI with no Ollama and no native services.
"""

import json

import pytest

from app import mcp_client, multi_agent_client
from app.config import Config

from test_mcp_rag_backend import FakeResponse, shared_tools

READINESS_POLICY = {
    "status": "ok",
    "answer": "A listing is ready to publish when it is active, has a valid category "
    "and price, and has a description of at least eight words.",
    "sources": [
        {
            "source": "product-catalogue-policy.md",
            "section": "Listing Readiness",
            "snippet": "A listing is ready to publish when it is active, has a valid "
            "category and price, and has a description of at least eight words.",
            "metadata": {"feature": "product_catalogue"},
        }
    ],
    "confidence": "high",
}

WORKFLOW = {
    "workflow_id": "wf-1",
    "subject_ref": "student-1-product:1",
    "status": "human_review",
    "stage": "human_review",
    "evidence": [],
}


@pytest.fixture()
def multi_agent(monkeypatch, fake_db):
    """Multi-Agent enabled, with an in-memory stand-in for the shared server."""
    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    state = {"calls": [], "workflows": {"wf-1": dict(WORKFLOW)}, "fail": False}

    def request(method, url, timeout=None, json=None, params=None):
        if state["fail"]:
            raise multi_agent_client.requests.ConnectionError("connection refused")
        path = url[len(Config.MULTI_AGENT_URL):]
        state["calls"].append({"method": method, "path": path, "json": json, "params": params})
        if method == "POST" and path == "/workflow":
            return FakeResponse({"workflow_id": "wf-2", "status": "queued"}, 202)
        if method == "GET" and path == "/workflow/history":
            items = [w for w in state["workflows"].values()
                     if w["subject_ref"] == params["subject_ref"]]
            return FakeResponse({"count": len(items), "workflows": items})
        if method == "GET" and path.startswith("/workflow/"):
            workflow = state["workflows"].get(path.rsplit("/", 1)[-1])
            if workflow is None:
                return FakeResponse({"error": "workflow not found"}, 404)
            return FakeResponse(workflow)
        if method == "POST" and path.endswith("/review"):
            workflow = state["workflows"][path.split("/")[2]]
            if workflow["status"] != "human_review":
                return FakeResponse({"error": "workflow is not awaiting human review"}, 409)
            workflow.update(status="accepted", human_decision=json)
            return FakeResponse(workflow)
        raise AssertionError("unexpected Multi-Agent call {} {}".format(method, path))

    monkeypatch.setattr(multi_agent_client.requests, "request", request)
    return state


def _evidence(call):
    return {item["id"]: item for item in call["json"]["evidence"]}


# --------------------------------------------------------------- start review
def test_start_sends_product_mcp_and_policy_evidence(backend, multi_agent, monkeypatch):
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(
        mcp_client, "_execute", lambda arguments: shared_tools.check_product_listing(**arguments)
    )
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        multi_agent_client.rag_client.requests, "post",
        lambda url, json=None, timeout=None: FakeResponse(READINESS_POLICY),
    )

    response = backend.post("/api/products/1/multi-agent", json={})

    assert response.status_code == 202
    assert response.get_json() == {"workflow_id": "wf-2", "status": "queued"}
    call = multi_agent["calls"][0]
    assert call["json"]["subject_ref"] == "student-1-product:1"
    evidence = _evidence(call)
    assert set(evidence) == {"product_facts", "mcp_listing", "catalogue_policy"}
    assert all(item["status"] == "available" for item in evidence.values())
    facts = json.loads(evidence["product_facts"]["content"])
    assert facts["sku"] == "SKU-AUD-1001" and facts["price_aud"] == 199.95
    assert json.loads(evidence["mcp_listing"]["content"])["tool"] == "check_product_listing"
    request = call["json"]["request"]
    assert request["worker_policy_evidence_ids"] == ["catalogue_policy"]
    assert request["plan_contract"]["constraints"]


def test_start_marks_disabled_mcp_and_rag_as_unavailable(backend, multi_agent):
    """MCP/RAG outages become explicit evidence, never silently dropped."""
    response = backend.post("/api/products/1/multi-agent", json={})

    assert response.status_code == 202
    evidence = _evidence(multi_agent["calls"][0])
    assert evidence["product_facts"]["status"] == "available"
    assert evidence["mcp_listing"]["status"] == "unavailable"
    assert evidence["catalogue_policy"]["status"] == "unavailable"


def test_policy_without_the_readiness_section_is_insufficient(backend, multi_agent, monkeypatch):
    other = dict(READINESS_POLICY, sources=[dict(READINESS_POLICY["sources"][0], section="Pricing Rules")])
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        multi_agent_client.rag_client.requests, "post",
        lambda url, json=None, timeout=None: FakeResponse(other),
    )

    backend.post("/api/products/1/multi-agent", json={})

    assert _evidence(multi_agent["calls"][0])["catalogue_policy"]["status"] == "insufficient"


def test_start_disabled_returns_503(backend, fake_db):
    response = backend.post("/api/products/1/multi-agent", json={})
    assert response.status_code == 503
    assert response.get_json()["detail"] == "Multi-Agent integration is disabled"


def test_start_unreachable_returns_503(backend, multi_agent):
    multi_agent["fail"] = True
    response = backend.post("/api/products/1/multi-agent", json={})
    assert response.status_code == 503
    assert "unreachable" in response.get_json()["detail"]


def test_start_unknown_product_is_404_without_calling_the_server(backend, multi_agent):
    assert backend.post("/api/products/999/multi-agent", json={}).status_code == 404
    assert multi_agent["calls"] == []


# --------------------------------------------------------- status and history
def test_status_returns_the_workflow(backend, multi_agent):
    response = backend.get("/api/products/1/multi-agent/wf-1")
    assert response.status_code == 200
    assert response.get_json()["status"] == "human_review"


def test_status_of_another_products_workflow_is_404(backend, multi_agent):
    """A workflow id cannot be read through a different product's URL."""
    response = backend.get("/api/products/2/multi-agent/wf-1")
    assert response.status_code == 404


def test_unknown_workflow_is_404(backend, multi_agent):
    assert backend.get("/api/products/1/multi-agent/missing").status_code == 404


def test_history_is_filtered_to_the_product(backend, multi_agent):
    response = backend.get("/api/products/1/multi-agent/history")
    assert response.get_json()["count"] == 1
    assert multi_agent["calls"][0]["params"] == {"subject_ref": "student-1-product:1"}


# --------------------------------------------------------------- human review
def test_review_records_the_human_decision(backend, multi_agent):
    response = backend.post(
        "/api/products/1/multi-agent/wf-1/review",
        json={"decision": "accept", "feedback": "Ready to publish."},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "accepted"
    assert body["human_decision"]["feedback"] == "Ready to publish."


def test_review_twice_is_409(backend, multi_agent):
    backend.post("/api/products/1/multi-agent/wf-1/review", json={"decision": "accept"})
    response = backend.post(
        "/api/products/1/multi-agent/wf-1/review", json={"decision": "reject"}
    )
    assert response.status_code == 409


def test_review_requires_a_json_object(backend, multi_agent):
    response = backend.post(
        "/api/products/1/multi-agent/wf-1/review", data="accept",
        content_type="text/plain",
    )
    assert response.status_code == 400


def test_health_reports_multi_agent_disabled(backend, fake_db):
    assert backend.get("/health").get_json()["multi_agent_server"] == {"status": "disabled"}


def test_readiness_rules_are_checked_by_the_application(backend, multi_agent, monkeypatch):
    """The agents get each Listing Readiness rule's result, not a sum to work out."""
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(
        mcp_client, "_execute", lambda arguments: shared_tools.check_product_listing(**arguments)
    )
    backend.post("/api/products/1/multi-agent", json={})  # "Over-ear headphones." = 2 words

    call = multi_agent["calls"][0]
    facts = json.loads(_evidence(call)["product_facts"]["content"])
    assert facts["readiness_checks"] == {
        "status_is_active": True,
        "category_is_valid": True,
        "price_within_1_to_9999_aud": True,
        "description_has_at_least_8_words": False,
    }
    assert facts["failed_checks"] == ["description_has_at_least_8_words"]
    assert call["json"]["request"]["worker_evidence_ids"] == ["product_facts", "catalogue_policy"]
    mcp = json.loads(_evidence(call)["mcp_listing"]["content"])
    assert "price_position" not in mcp and "price_vs_average_pct" not in mcp
    assert mcp["listing_status"] in ("ready", "needs_attention", "invalid")


def _checked(recommendation, failed_checks):
    return multi_agent_client.application_check({
        "worker_result": {"recommendation": recommendation},
        "evidence": [{"id": "product_facts",
                      "content": json.dumps({"failed_checks": failed_checks})}],
    })


@pytest.mark.parametrize("recommendation, failed, verdict, agrees", [
    ("The lamp is ready to publish.", [], "ready", True),
    ("The charger is not ready: its status is draft.", ["status_is_active"], "not ready", True),
    ("The charger is ready to publish.", ["status_is_active"], "ready", False),
    ("The lamp is not yet ready.", [], "not ready", False),
    ("Review the listing.", [], None, None),
])
def test_application_cross_checks_the_worker_verdict(recommendation, failed, verdict, agrees):
    check = _checked(recommendation, failed)
    assert check["worker_verdict"] == verdict
    assert check["agrees"] is agrees
    assert check["expected"] == ("not ready" if failed else "ready")


def test_status_carries_the_application_check(backend, multi_agent):
    multi_agent["workflows"]["wf-1"].update(
        worker_result={"recommendation": "It is ready to publish."},
        evidence=[{"id": "product_facts", "content": json.dumps({"failed_checks": []})}],
    )
    body = backend.get("/api/products/1/multi-agent/wf-1").get_json()
    assert body["application_check"]["agrees"] is True
