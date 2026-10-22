"""Unit tests for the shared Multi-Agent workflow (Planner -> Worker -> Reviewer).

The LLM is replaced by a stub client so the tests run offline in GitHub Actions
(no Ollama container in CI), matching ai-services/ai-mode/tests/test_agentic_loop.py.

Run from the repository root: pytest ai-services/multi-agent/tests -v
"""

import json
import os
import sys

import pytest

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from agent.ollama_client import OllamaError  # noqa: E402
from agent.workflow import MultiAgentWorkflow, WorkflowRequest  # noqa: E402


class StubClient:
    """Returns canned answers in order; records the prompts it was given."""

    model = "stub-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, system=None, json_mode=True, temperature=0.4):
        self.prompts.append(prompt)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


OUTPUT_SCHEMA = {
    "summary": {"type": "string", "min_words": 3, "max_words": 40},
}


def make_request(**overrides):
    payload = {
        "goal": "restock_plan",
        "task": "Summarise whether this product should be restocked.",
        "context": {"stock_level": 4, "reorder_threshold": 10},
        "output_schema": OUTPUT_SCHEMA,
        "fallback": {"summary": "Fallback summary pending manual review."},
    }
    payload.update(overrides)
    return WorkflowRequest.from_json(payload)


def test_workflow_request_requires_task():
    with pytest.raises(ValueError):
        WorkflowRequest.from_json({"output_schema": OUTPUT_SCHEMA})


def test_workflow_request_requires_output_schema():
    with pytest.raises(ValueError):
        WorkflowRequest.from_json({"task": "do something"})


def test_full_workflow_reaches_pending_human_review():
    client = StubClient([
        json.dumps({
            "steps": [
                "Check stock level against the reorder threshold",
                "Recommend an action",
            ]
        }),
        json.dumps({
            "summary": "Stock is below the reorder threshold and should be restocked soon."
        }),
        json.dumps({
            "verdict": "approve",
            "recommendation": "Looks correct and safe to send.",
            "risks": [],
        }),
    ])
    workflow = MultiAgentWorkflow(client=client)
    outcome = workflow.run(make_request())

    assert outcome["status"] == "pending_human_review"
    assert outcome["plan"]["ok"] is True
    assert len(outcome["plan"]["steps"]) == 2
    assert outcome["worker"]["ok"] is True
    assert outcome["review"]["verdict"] == "approve"
    assert len(outcome["trace"]) == 3
    assert [step["step"] for step in outcome["trace"]] == ["Planner", "Worker", "Reviewer"]


def test_planner_falls_back_when_ollama_unreachable():
    client = StubClient([OllamaError("offline")])
    workflow = MultiAgentWorkflow(client=client)
    plan = workflow.plan(make_request())
    assert plan["ok"] is False
    assert plan["steps"]  # deterministic fallback still gives a usable plan


def test_planner_rejects_a_single_step_plan():
    # PLAN_SCHEMA requires at least 2 steps; a lone step is a guardrail
    # violation, so the Planner falls back rather than passing it through.
    client = StubClient([json.dumps({"steps": ["only one step"]})])
    workflow = MultiAgentWorkflow(client=client)
    plan = workflow.plan(make_request())
    assert plan["ok"] is False


def test_worker_falls_back_to_caller_supplied_fallback_on_error():
    client = StubClient([OllamaError("offline")])
    workflow = MultiAgentWorkflow(client=client)
    request_obj = make_request()
    work = workflow.work(request_obj, {"steps": ["step one", "step two"]})
    assert work["ok"] is False
    assert work["result"] == request_obj.fallback


def test_worker_rejects_output_that_fails_the_schema():
    # "x" is 1 word; OUTPUT_SCHEMA requires at least 3.
    client = StubClient([json.dumps({"summary": "x"})])
    workflow = MultiAgentWorkflow(client=client)
    request_obj = make_request()
    work = workflow.work(request_obj, {"steps": ["step one", "step two"]})
    assert work["ok"] is False
    assert work["result"] == request_obj.fallback


def test_reviewer_recommends_revise_when_unavailable():
    client = StubClient([OllamaError("offline")])
    workflow = MultiAgentWorkflow(client=client)
    request_obj = make_request()
    review = workflow.review(
        request_obj, {"steps": ["step one"]}, {"result": {"summary": "restock soon"}}
    )
    assert review["ok"] is False
    assert review["verdict"] == "revise"


def test_reviewer_parses_a_reject_verdict_with_risks():
    client = StubClient([
        json.dumps({
            "verdict": "reject",
            "recommendation": "Do not send this to the customer yet.",
            "risks": ["price contradicts the supplied context"],
        })
    ])
    workflow = MultiAgentWorkflow(client=client)
    request_obj = make_request()
    review = workflow.review(
        request_obj, {"steps": ["step one"]}, {"result": {"summary": "restock soon"}}
    )
    assert review["ok"] is True
    assert review["verdict"] == "reject"
    assert review["risks"] == ["price contradicts the supplied context"]
