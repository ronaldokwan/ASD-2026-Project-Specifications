"""Release 2: the Multi-Agent listing review panel in the frontend microservice."""

import pytest
from api_client import ApiError

import conftest

api = conftest.frontend_api

COMPLETED_STAGES = {
    "workflow_id": "wf-1",
    "subject_ref": "student-1-product:1",
    "status": "human_review",
    "stage": "human_review",
    "created_at": "2026-10-22T10:00:00+00:00",
    "roles": [
        {"role": "planner", "model": "llama3.1:8b"},
        {"role": "worker", "model": "qwen2.5:3b"},
        {"role": "reviewer", "model": "llama3.1:8b"},
    ],
    "revision_count": 0,
    "max_revisions": 1,
    "plan": {
        "model_generated": {"tasks": [
            {"task": "Compare stored fields with the readiness rule.",
             "evidence_refs": ["product_facts", "catalogue_policy"]},
        ]},
        "application_enforced": {
            "acceptance_criteria": ["Judge readiness only against catalogue_policy."],
            "constraints": ["Do not edit, publish, archive or delete the product."],
        },
    },
    "worker_result": {
        "recommendation": "Aurora Wireless Headphones is ready to publish.",
        "rationale": "It is active, priced in range and has a long enough description.",
        "policy_basis": "catalogue_policy",
        "evidence_refs": ["product_facts", "catalogue_policy"],
        "application_added_evidence_refs": [],
    },
    "reviewer_result": {
        "action": "ready_for_human",
        "claim_assessment": {"recommendation": "supported", "rationale": "supported",
                             "consistency": "consistent"},
        "findings": [],
        "missing_information": [],
        "recommendations": [],
    },
    "evidence": [{"id": "product_facts", "source": "student-1-product-api",
                  "status": "available", "content": "{}"}],
    "human_decision": None,
}


@pytest.fixture()
def workflow_api(monkeypatch, fake_api):
    state = {"workflow": dict(COMPLETED_STAGES), "reviews": []}
    monkeypatch.setattr(api, "start_multi_agent_review",
                        lambda pid: {"workflow_id": "wf-1", "status": "queued"})
    monkeypatch.setattr(api, "get_multi_agent_workflow", lambda pid, wid: state["workflow"])
    monkeypatch.setattr(api, "list_multi_agent_workflows",
                        lambda pid: {"count": 1, "workflows": [state["workflow"]]})

    def review(pid, wid, payload):
        state["reviews"].append(payload)
        status = {"accept": "accepted", "partial_accept": "partially_accepted",
                  "reject": "rejected"}[payload["decision"]]
        state["workflow"] = dict(state["workflow"], status=status, stage="completed",
                                 human_decision=dict(payload, reviewed_at="2026-10-22T10:05:00"))
        return state["workflow"]

    monkeypatch.setattr(api, "review_multi_agent_workflow", review)
    return state


def test_index_has_the_multi_agent_panel_and_review_button(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert 'id="multi-agent-panel"' in html
    assert 'hx-post="/products/1/multi-agent"' in html


def test_start_shows_planner_worker_reviewer_and_human_review(frontend, workflow_api):
    html = frontend.post("/products/1/multi-agent").get_data(as_text=True)
    assert "1. Planner" in html and "Compare stored fields" in html
    assert "2. Worker" in html and "ready to publish" in html
    assert "3. Reviewer" in html and "ready for human" in html
    assert "4. Human review" in html
    for decision in ("accept", "partial_accept", "reject"):
        assert 'name="decision" value="{}"'.format(decision) in html
    assert "llama3.1:8b" in html


def test_running_workflow_polls_and_hides_the_decision(frontend, workflow_api):
    workflow_api["workflow"] = dict(COMPLETED_STAGES, status="working", stage="worker",
                                    worker_result=None, reviewer_result=None)
    html = frontend.get("/products/1/multi-agent/wf-1").get_data(as_text=True)
    assert 'hx-get="/products/1/multi-agent/wf-1"' in html
    assert "4. Human review" not in html


def test_accept_records_the_decision(frontend, workflow_api):
    html = frontend.post("/products/1/multi-agent/wf-1/review",
                         data={"decision": "accept", "feedback": "Looks right."}).get_data(as_text=True)
    assert workflow_api["reviews"] == [{"decision": "accept", "feedback": "Looks right."}]
    assert "4. Human review &middot; accept" in html
    assert 'value="accept"' not in html


def test_partial_accept_sends_corrections(frontend, workflow_api):
    frontend.post("/products/1/multi-agent/wf-1/review", data={
        "decision": "partial_accept",
        "feedback": "Price note needed.",
        "corrected_recommendation": "Ready, but review the price.",
        "corrected_rationale": "Price is above comparable products.",
        "accepted_fields": "recommendation\n\nrationale\n",
        "unresolved_issues": "Price above range",
    })
    payload = workflow_api["reviews"][0]
    assert payload["corrected_output"]["recommendation"] == "Ready, but review the price."
    assert payload["accepted_fields"] == ["recommendation", "rationale"]
    assert payload["unresolved_issues"] == ["Price above range"]


def test_rejected_review_keeps_the_form_and_shows_the_error(frontend, workflow_api, monkeypatch):
    def fail(pid, wid, payload):
        raise ApiError("rejection requires feedback", 400)

    monkeypatch.setattr(api, "review_multi_agent_workflow", fail)
    html = frontend.post("/products/1/multi-agent/wf-1/review",
                         data={"decision": "reject"}).get_data(as_text=True)
    assert "rejection requires feedback" in html
    assert 'value="reject"' in html


def test_server_outage_is_reported(frontend, fake_api, monkeypatch):
    def down(pid):
        raise ApiError("Multi-Agent server unavailable", 503)

    monkeypatch.setattr(api, "start_multi_agent_review", down)
    html = frontend.post("/products/1/multi-agent").get_data(as_text=True)
    assert "Multi-Agent server unavailable" in html
    assert "run-ai-services.sh" in html


def test_history_lists_earlier_workflows(frontend, workflow_api):
    html = frontend.get("/products/1/multi-agent/history").get_data(as_text=True)
    assert "human review" in html
    assert 'hx-get="/products/1/multi-agent/wf-1"' in html


def test_reconciled_reviewer_output_is_flagged_for_the_human(frontend, workflow_api):
    workflow_api["workflow"] = dict(COMPLETED_STAGES, reviewer_result={
        "action": "not_supported", "reconciled": True,
        "claim_assessment": {"recommendation": "unsupported", "rationale": "unsupported",
                             "consistency": "not_applicable"},
        "findings": [{"severity": "high", "finding": "Reviewer output stayed internally inconsistent.",
                      "evidence_ref": None}],
        "missing_information": [], "recommendations": [],
    })
    html = frontend.get("/products/1/multi-agent/wf-1").get_data(as_text=True)
    assert "contradicted itself on every attempt" in html
    assert 'name="decision" value="accept"' in html


def test_application_check_shows_a_wrong_worker_verdict(frontend, workflow_api):
    workflow_api["workflow"] = dict(COMPLETED_STAGES, application_check={
        "expected": "not ready", "failed_checks": ["status_is_active"],
        "worker_verdict": "ready", "agrees": False,
    })
    html = frontend.get("/products/1/multi-agent/wf-1").get_data(as_text=True)
    assert "Application cross-check" in html
    assert "because the status is not active" in html
    assert "it is wrong" in html


def test_view_scrolls_to_the_workflow_and_marks_the_one_being_viewed(frontend, workflow_api):
    """View sits under a tall panel, so it must scroll back up to what it opened."""
    html = frontend.get("/products/1/multi-agent/history").get_data(as_text=True)
    assert 'hx-swap="innerHTML show:#multi-agent-card:top"' in html

    html = frontend.get("/products/1/multi-agent/history?current=wf-1").get_data(as_text=True)
    assert "viewing" in html
    assert 'hx-get="/products/1/multi-agent/wf-1"' not in html


def test_workflow_panel_asks_history_to_mark_itself(frontend, workflow_api):
    html = frontend.get("/products/1/multi-agent/wf-1").get_data(as_text=True)
    assert "/products/1/multi-agent/history?current=wf-1" in html


def test_running_workflow_refreshes_only_itself(frontend, workflow_api):
    workflow_api["workflow"] = dict(COMPLETED_STAGES, status="reviewing", stage="reviewer")
    html = frontend.get("/products/1/multi-agent/wf-1").get_data(as_text=True)
    assert 'hx-target="this" hx-swap="outerHTML"' in html


def test_scroll_to_results_is_instant(frontend, fake_api):
    """htmx's default smooth scroll is dropped by some browsers, hiding the result."""
    html = frontend.get("/").get_data(as_text=True)
    assert '<meta name="htmx-config" content=\'{"scrollBehavior": "auto"}\'>' in html
