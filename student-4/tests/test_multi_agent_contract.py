"""Contract test between Student 4 and the real shared workflow service."""

import importlib.util
import os
from types import SimpleNamespace

import pytest

from app import multi_agent_client
from app.config import Config


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = importlib.util.spec_from_file_location(
    "student4_shared_multi_agent",
    os.path.join(ROOT, "ai-services", "multi-agent", "service.py"),
)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)

MODEL_OUTPUT = {
    "planner": {"tasks": [{
        "task": "Compare the current quantity with its reorder threshold.",
        "evidence_refs": ["stock_facts", "stock_policy"],
    }]},
    "worker": {
        "recommendation": "This item should be reordered.",
        "rationale": "The recorded quantity is below the reorder threshold.",
        "policy_basis": "stock_policy",
        "evidence_refs": ["stock_facts", "stock_policy"],
    },
    "reviewer": {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "supported",
            "rationale": "supported",
            "consistency": "consistent",
        },
        "findings": [],
        "missing_information": [],
        "recommendations": [],
    },
}


class ImmediateExecutor:
    def submit(self, function, workflow_id):
        function(workflow_id)


@pytest.fixture()
def shared_server(tmp_path, monkeypatch, fake_db):
    monkeypatch.setattr(service, "HISTORY_PATH", tmp_path / "workflow_history.jsonl")
    monkeypatch.setattr(service, "AUDIT_PATH", tmp_path / "coordination_audit.jsonl")
    monkeypatch.setattr(service, "_executor", ImmediateExecutor())
    roles = []

    def call_model(role, _prompt):
        roles.append(role)
        return service.ROLE_MODELS[role], MODEL_OUTPUT[role]

    monkeypatch.setattr(service, "_call_model", call_model)
    server = service.create_app().test_client()

    def request(method, url, timeout=None, json=None, params=None):
        path = url[len(Config.MULTI_AGENT_URL):]
        response = server.open(path, method=method, json=json, query_string=params)
        return SimpleNamespace(
            status_code=response.status_code,
            json=response.get_json,
        )

    monkeypatch.setattr(Config, "MULTI_AGENT_ENABLED", True)
    monkeypatch.setattr(multi_agent_client.requests, "request", request)
    return {"server": server, "roles": roles}


def test_real_shared_service_runs_roles_and_records_human_decision(
    backend, shared_server
):
    started = backend.post("/api/stock/1/multi-agent", json={})
    assert started.status_code == 202, started.get_json()
    workflow_id = started.get_json()["workflow_id"]

    workflow = backend.get(
        "/api/stock/1/multi-agent/{}".format(workflow_id)
    ).get_json()
    assert shared_server["roles"] == ["planner", "worker", "reviewer"]
    assert workflow["status"] == "human_review"
    assert workflow["subject_ref"] == "student-4-stock:1"
    assert {item["id"] for item in workflow["evidence"]} == {
        "stock_facts", "stock_policy", "mcp_reorder",
    }

    reviewed = backend.post(
        "/api/stock/1/multi-agent/{}/review".format(workflow_id),
        json={"decision": "accept", "feedback": "Reviewed."},
    )
    assert reviewed.status_code == 200
    assert reviewed.get_json()["status"] == "accepted"
