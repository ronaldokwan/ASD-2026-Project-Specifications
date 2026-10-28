"""Frontend tests for the HTMX multi-agent stock-review flow."""

import pytest
from api_client import ApiError

import conftest

api = conftest.frontend_api

WORKFLOW = {
    "workflow_id": "wf-1",
    "subject_ref": "student-4-stock:1",
    "status": "human_review",
    "stage": "human_review",
    "roles": [{"role": "planner", "model": "llama3.1:8b"}],
    "revision_count": 0,
    "max_revisions": 1,
    "plan": {
        "model_generated": {
            "tasks": [{
                "task": "Compare the recorded quantity with its reorder threshold.",
                "evidence_refs": ["stock_facts", "stock_policy"],
            }],
        },
        "application_enforced": {
            "acceptance_criteria": ["Use the recorded quantity and threshold."],
            "constraints": ["Do not place an order."],
        },
    },
    "worker_result": {
        "recommendation": "Reorder this item.",
        "rationale": "Its quantity is below the recorded threshold.",
        "policy_basis": "stock_policy",
        "evidence_refs": ["stock_facts", "stock_policy", "mcp_reorder"],
    },
    "reviewer_result": {
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
    "evidence": [],
    "human_decision": None,
}


@pytest.fixture()
def workflow_api(monkeypatch, fake_api):
    state = {"workflow": dict(WORKFLOW), "reviews": []}
    monkeypatch.setattr(
        api, "start_multi_agent_review",
        lambda stock_id: {"workflow_id": "wf-1", "status": "queued"},
    )
    monkeypatch.setattr(
        api, "get_multi_agent_workflow",
        lambda stock_id, workflow_id: state["workflow"],
    )
    monkeypatch.setattr(
        api, "list_multi_agent_workflows",
        lambda stock_id: {"count": 1, "workflows": [state["workflow"]]},
    )

    def review(stock_id, workflow_id, payload):
        state["reviews"].append(payload)
        state["workflow"] = dict(
            state["workflow"],
            status={"accept": "accepted", "partial_accept": "partially_accepted",
                    "reject": "rejected"}[payload["decision"]],
            human_decision=dict(payload, reviewed_at="2026-10-28T10:00:00"),
        )
        return state["workflow"]

    monkeypatch.setattr(api, "review_multi_agent_workflow", review)
    return state


def test_inventory_page_exposes_review_button(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert 'id="multi-agent-panel"' in html
    assert 'hx-post="/stock/1/multi-agent"' in html


def test_review_renders_all_agent_stages_and_human_decisions(frontend, workflow_api):
    html = frontend.post("/stock/1/multi-agent").get_data(as_text=True)
    for text in ("1. Planner", "2. Worker", "3. Reviewer", "4. Human review"):
        assert text in html
    assert "Compare the recorded quantity" in html
    assert "Do not place an order." in html
    for decision in ("accept", "partial_accept", "reject"):
        assert 'name="decision" value="{}"'.format(decision) in html


def test_running_workflow_polls_until_human_review(frontend, workflow_api):
    workflow_api["workflow"] = dict(
        WORKFLOW, status="working", stage="worker",
        worker_result=None, reviewer_result=None,
    )
    html = frontend.get("/stock/1/multi-agent/wf-1").get_data(as_text=True)
    assert 'hx-get="/stock/1/multi-agent/wf-1"' in html
    assert "4. Human review" not in html


def test_partial_accept_sends_corrections_and_issues(frontend, workflow_api):
    frontend.post("/stock/1/multi-agent/wf-1/review", data={
        "decision": "partial_accept",
        "feedback": "Correct the quantity.",
        "corrected_recommendation": "Review a reorder.",
        "corrected_rationale": "MCP evidence is unavailable.",
        "accepted_fields": "recommendation\n",
        "unresolved_issues": "Confirm supplier availability.\n",
    })
    payload = workflow_api["reviews"][0]
    assert payload["corrected_output"]["recommendation"] == "Review a reorder."
    assert payload["accepted_fields"] == ["recommendation"]
    assert payload["unresolved_issues"] == ["Confirm supplier availability."]


def test_review_errors_remain_visible(frontend, workflow_api, monkeypatch):
    def fail(stock_id, workflow_id, payload):
        raise ApiError("reject requires feedback", 400)

    monkeypatch.setattr(api, "review_multi_agent_workflow", fail)
    html = frontend.post(
        "/stock/1/multi-agent/wf-1/review", data={"decision": "reject"}
    ).get_data(as_text=True)
    assert "reject requires feedback" in html
    assert 'value="reject"' in html


def test_history_lists_earlier_workflows(frontend, workflow_api):
    html = frontend.get("/stock/1/multi-agent/history").get_data(as_text=True)
    assert "human review" in html
    assert 'hx-get="/stock/1/multi-agent/wf-1"' in html


def test_server_outage_is_reported(frontend, fake_api, monkeypatch):
    def down(stock_id):
        raise ApiError("Multi-Agent server unavailable", 503)

    monkeypatch.setattr(api, "start_multi_agent_review", down)
    html = frontend.post("/stock/1/multi-agent").get_data(as_text=True)
    assert "Multi-Agent server unavailable" in html
