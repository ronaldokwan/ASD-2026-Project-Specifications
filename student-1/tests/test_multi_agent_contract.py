"""Release 2 contract test: Student 1 backend -> the real shared Multi-Agent server.

Only the Ollama model calls are stubbed. The shared server's own request
validation, Planner/Worker/Reviewer output validators, completion gate, human
review and history/audit logs all run, so a change on either side that breaks
the listing review fails here.
"""

import importlib.util
import json
import os

import pytest

from app import mcp_client, multi_agent_client
from app.config import Config

from test_mcp_rag_backend import FakeResponse, shared_tools
from test_multi_agent_backend import READINESS_POLICY

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "shared_multi_agent_service",
    os.path.join(REPO_ROOT, "ai-services", "multi-agent", "service.py"),
)
service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(service)

MODEL_OUTPUT = {
    "planner": {"tasks": [
        {"task": "Read the stored status, price and description length.",
         "evidence_refs": ["product_facts"]},
        {"task": "Compare them with the Listing Readiness rule and the MCP issues.",
         "evidence_refs": ["catalogue_policy", "mcp_listing"]},
    ]},
    "worker": {
        "recommendation": "Aurora Wireless Headphones is not ready to publish yet.",
        "rationale": "The description has three words; the policy requires at least eight.",
        "policy_basis": "catalogue_policy",
        "evidence_refs": ["product_facts", "catalogue_policy"],
    },
    "reviewer": {
        "action": "ready_for_human",
        "claim_assessment": {"recommendation": "supported", "rationale": "supported",
                             "consistency": "consistent"},
        "findings": [],
        "missing_information": [],
        "recommendations": ["Extend the description before publishing."],
    },
}


class ImmediateExecutor:
    def submit(self, function, workflow_id):
        function(workflow_id)


@pytest.fixture()
def shared_server(tmp_path, monkeypatch, fake_db):
    """MCP, RAG and Multi-Agent on; the Multi-Agent hop goes to the real app."""
    monkeypatch.setattr(service, "HISTORY_PATH", tmp_path / "workflow_history.jsonl")
    monkeypatch.setattr(service, "AUDIT_PATH", tmp_path / "coordination_audit.jsonl")
    monkeypatch.setattr(service, "_executor", ImmediateExecutor())
    roles = []

    def call_model(role, prompt):
        roles.append(role)
        return service.ROLE_MODELS[role], MODEL_OUTPUT[role]

    monkeypatch.setattr(service, "_call_model", call_model)
    server = service.create_app().test_client()

    def request(method, url, timeout=None, json=None, params=None):
        path = url[len(Config.MULTI_AGENT_URL):]
        response = server.open(path, method=method, json=json, query_string=params)
        return FakeResponse(response.get_json(), response.status_code)

    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    monkeypatch.setattr(multi_agent_client.requests, "request", request)
    monkeypatch.setattr(Config, "MCP_ENABLED", True)
    monkeypatch.setattr(
        mcp_client, "_execute", lambda arguments: shared_tools.check_product_listing(**arguments)
    )
    monkeypatch.setattr(Config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        multi_agent_client.rag_client.requests, "post",
        lambda url, json=None, timeout=None: FakeResponse(READINESS_POLICY),
    )
    return {"roles": roles, "dir": tmp_path}


def test_listing_review_runs_planner_worker_reviewer_then_human(backend, shared_server):
    started = backend.post("/api/products/1/multi-agent", json={})
    assert started.status_code == 202, started.get_json()
    workflow_id = started.get_json()["workflow_id"]

    workflow = backend.get("/api/products/1/multi-agent/" + workflow_id).get_json()
    assert shared_server["roles"] == ["planner", "worker", "reviewer"]
    assert workflow["status"] == "human_review", workflow.get("failure")
    assert workflow["completion_gate"] == {
        "planner_completed": True, "worker_completed": True,
        "reviewer_completed": True, "human_decision_recorded": False,
    }
    assert {item["status"] for item in workflow["evidence"]} == {"available"}

    decided = backend.post(
        "/api/products/1/multi-agent/{}/review".format(workflow_id),
        json={"decision": "accept", "feedback": "Agreed: extend the description first."},
    )
    assert decided.status_code == 200
    assert decided.get_json()["status"] == "accepted"
    assert decided.get_json()["completion_gate"]["human_decision_recorded"] is True

    history = backend.get("/api/products/1/multi-agent/history").get_json()
    assert [item["workflow_id"] for item in history["workflows"]] == [workflow_id]
    events = [json.loads(line)["event"] for line in
              (shared_server["dir"] / "coordination_audit.jsonl").read_text().splitlines()]
    assert events[0] == "workflow_created" and events[-1] == "human_decision_recorded"
    assert "human_review_required" in events


def test_a_second_review_is_refused_by_the_shared_server(backend, shared_server):
    workflow_id = backend.post("/api/products/1/multi-agent", json={}).get_json()["workflow_id"]
    url = "/api/products/1/multi-agent/{}/review".format(workflow_id)
    assert backend.post(url, json={"decision": "reject", "feedback": "No."}).status_code == 200

    assert backend.post(url, json={"decision": "accept"}).status_code == 409


def test_partial_accept_without_corrections_is_rejected_by_the_server(backend, shared_server):
    workflow_id = backend.post("/api/products/1/multi-agent", json={}).get_json()["workflow_id"]

    response = backend.post(
        "/api/products/1/multi-agent/{}/review".format(workflow_id),
        json={"decision": "partial_accept", "feedback": "Needs edits."},
    )

    assert response.status_code == 400
    assert "corrected_output" in response.get_json()["error"]
