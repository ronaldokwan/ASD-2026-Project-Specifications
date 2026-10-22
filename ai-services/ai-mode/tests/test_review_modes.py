"""Deterministic evidence gates and review logging for the shared review modes."""

import sys
from pathlib import Path

import pytest


SERVICE_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, SERVICE_ROOT)

import app as ai_app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_app, "_review_dir", tmp_path)
    monkeypatch.setattr(ai_app, "_review_history", tmp_path / "review_history.jsonl")
    monkeypatch.setattr(ai_app, "_validation_log", tmp_path / "review_validation.jsonl")
    return ai_app.app.test_client()


def _model_result(mode, assessment="passed"):
    common = {
        "assessment": assessment,
        "findings": "The supplied records are internally consistent.",
        "risks": "Unverified claims remain possible.",
        "recommendations": "Keep source evidence with the result.",
    }
    if mode == "testing_report":
        common.update({
            "test_code_review": "The code checks meaningful route behavior and returned data.",
            "execution_results_review": "Every supplied run has an explicit exit status.",
        })
    elif mode == "cloud_deployment_report":
        common.update({
            "assessment": "ready" if assessment == "passed" else assessment,
            "infrastructure_review": "The resource evidence lists the expected private boundaries.",
            "runtime_review": "Runtime checks include frontend, backend and database behavior.",
        })
    else:
        common.update({"workflow_review": "The plan, work, review and decision are recorded."})
    return common


def _run_review(monkeypatch, mode, subject, assessment="passed"):
    monkeypatch.setattr(ai_app.loop, "run", lambda _request: {
        "ok": True,
        "result": _model_result(mode, assessment),
        "fallback_used": False,
        "trace": [{"step": "Plan"}, {"step": "Act"}, {"step": "Observe"}],
    })
    return ai_app.app.test_client().post("/agent/validate", json={"mode": mode, "subject": subject})


def test_testing_report_security_failure_cannot_be_overruled_by_model(client, monkeypatch):
    response = _run_review(monkeypatch, "testing_report", {
        "test_code": "assert response.status_code == 200",
        "pre_commit_security_results": [
            {"name": "ruff-security", "status": "passed", "exit_code": 0},
            {"name": "detect-secrets", "status": "passed", "exit_code": 0},
            {"name": "pip-audit", "status": "failed", "exit_code": 1},
        ],
        "post_commit_backend_endpoint_tests": [
            {"endpoint": "GET /customers", "phase": "post_commit", "status": "passed", "exit_code": 0},
            {"endpoint": "POST /customers", "phase": "post_commit", "status": "passed", "exit_code": 0},
        ],
        "hosted_ci": {"status": "passed", "run_id": "run-123"},
    })
    result = response.get_json()
    assert response.status_code == 200
    assert result["result"]["assessment"] == "failed"
    assert result["result"]["validation_log"]["contradiction"] is True
    assert result["status"] == "blocked"
    assert "pip-audit" in result["result"]["findings"]
    assert "pip-audit" in result["result"]["execution_results_review"]
    assert len(ai_app._review_history.read_text().splitlines()) == 1
    assert len(ai_app._validation_log.read_text().splitlines()) == 1


def test_unavailable_security_tool_is_incomplete_not_a_vulnerability_finding(client, monkeypatch):
    response = _run_review(monkeypatch, "testing_report", {
        "test_code": "assert response.status_code == 200",
        "pre_commit_security_results": [
            {"name": "ruff-security", "status": "unavailable"},
            {"name": "detect-secrets", "status": "unavailable"},
            {"name": "pip-audit", "status": "unavailable"},
        ],
        "post_commit_backend_endpoint_tests": [
            {"endpoint": "GET /customers", "phase": "post_commit", "status": "passed"},
            {"endpoint": "POST /customers", "phase": "post_commit", "status": "passed"},
        ],
        "hosted_ci": {"status": "passed", "run_id": "run-123"},
    })
    result = response.get_json()
    assert result["result"]["assessment"] == "incomplete"
    assert "without a pass result" in result["result"]["validation_log"]["evidence_gate"]


def test_missing_testing_evidence_is_incomplete(client, monkeypatch):
    response = _run_review(monkeypatch, "testing_report", {
        "test_code": "assert True",
        "pre_commit_security_results": [
            {"name": "ruff-security", "status": "passed"},
            {"name": "detect-secrets", "status": "passed"},
            {"name": "pip-audit", "status": "passed"},
        ],
        "post_commit_backend_endpoint_tests": [],
    })
    result = response.get_json()
    assert result["result"]["assessment"] == "incomplete"
    assert result["status"] == "incomplete"
    assert "post-commit backend endpoint-test results are missing" in result["result"]["findings"]


def test_local_tests_do_not_count_as_post_commit_backend_evidence(client, monkeypatch):
    response = _run_review(monkeypatch, "testing_report", {
        "test_code": "assert response.status_code == 200",
        "pre_commit_security_results": [
            {"name": "ruff-security", "status": "passed"},
            {"name": "detect-secrets", "status": "passed"},
            {"name": "pip-audit", "status": "passed"},
        ],
        "post_commit_backend_endpoint_tests": [
            {"endpoint": "GET /customers", "phase": "local_uncommitted", "status": "passed"},
            {"endpoint": "POST /customers", "phase": "local_uncommitted", "status": "passed"},
        ],
        "hosted_ci": {"status": "not_run"},
    })
    result = response.get_json()
    assert result["result"]["assessment"] == "incomplete"
    assert "not identified as post-commit" in result["result"]["validation_log"]["evidence_gate"]
    assert "GitHub Actions" in result["result"]["validation_log"]["evidence_gate"]
    assert "local results, not post-commit executions" in result["result"]["execution_results_review"]


def test_testing_review_corrects_model_claim_that_local_tests_were_post_commit(client, monkeypatch):
    result = _model_result("testing_report")
    result["execution_results_review"] = "The endpoint tests were run post-commit and passed."
    monkeypatch.setattr(ai_app.loop, "run", lambda _request: {
        "ok": True, "result": result, "fallback_used": False, "trace": [],
    })
    response = client.post("/agent/validate", json={
        "mode": "testing_report",
        "subject": {
            "test_code": "assert response.status_code == 200",
            "pre_commit_security_results": [
                {"name": "ruff-security", "status": "passed"},
                {"name": "detect-secrets", "status": "passed"},
                {"name": "pip-audit", "status": "passed"},
            ],
            "post_commit_backend_endpoint_tests": [
                {"endpoint": "GET /customers", "phase": "local_uncommitted", "status": "passed"},
                {"endpoint": "POST /customers", "phase": "local_uncommitted", "status": "passed"},
            ],
            "hosted_ci": {"status": "not_run"},
        },
    })
    reviewed = response.get_json()["result"]
    assert reviewed["assessment"] == "incomplete"
    assert "local results, not post-commit executions" in reviewed["execution_results_review"]
    assert "not hosted CI results" in reviewed["execution_results_review"]


def test_complete_security_and_post_commit_endpoint_evidence_can_pass(client, monkeypatch):
    response = _run_review(monkeypatch, "testing_report", {
        "test_code": "assert response.status_code == 200",
        "pre_commit_security_results": [
            {"name": "ruff-security", "status": "passed", "exit_code": 0},
            {"name": "detect-secrets", "status": "passed", "exit_code": 0},
            {"name": "pip-audit", "status": "passed", "exit_code": 0},
        ],
        "post_commit_backend_endpoint_tests": [
            {"endpoint": "GET /customers", "phase": "post_commit", "status": "passed", "exit_code": 0},
            {"endpoint": "POST /customers", "phase": "post_commit", "status": "passed", "exit_code": 0},
        ],
        "hosted_ci": {"status": "passed", "run_id": "run-123"},
    })
    result = response.get_json()
    assert result["result"]["assessment"] == "passed"
    assert result["result"]["validation_log"]["evidence_assessment"] == "passed"


def test_testing_review_prompt_separates_local_results_from_hosted_ci():
    from agent.review_modes import task_for

    task = task_for("testing_report")
    assert "not hosted CI results" in task
    assert "post-commit local executions" in task


def test_cloud_review_requires_three_runtime_categories(client, monkeypatch):
    response = _run_review(monkeypatch, "cloud_deployment_report", {
        "infrastructure_evidence": [{"name": "cluster", "status": "passed"}],
        "runtime_checks": [{"check": "frontend", "status": "passed"}],
    })
    result = response.get_json()
    assert result["result"]["assessment"] == "incomplete"
    assert "backend/database and CRUD" in result["result"]["validation_log"]["evidence_gate"]


def test_workflow_review_requires_actual_human_decision(client, monkeypatch):
    response = _run_review(monkeypatch, "multi_agent_workflow", {
        "workflow": {
            "status": "human_review",
            "completion_gate": {
                "planner_completed": True, "worker_completed": True,
                "reviewer_completed": True, "human_decision_recorded": False,
            },
        },
    }, assessment="supported")
    result = response.get_json()
    assert result["result"]["assessment"] == "incomplete"
    assert result["status"] == "incomplete"


def test_unavailable_model_is_not_reported_as_success(client, monkeypatch):
    monkeypatch.setattr(ai_app.loop, "run", lambda _request: {
        "ok": True, "result": {"assessment": "passed"}, "fallback_used": True,
        "trace": [],
    })
    response = ai_app.app.test_client().post("/agent/validate", json={
        "mode": "testing_report",
        "subject": {"test_code": "assert True", "execution_results": [{"status": "passed", "exit_code": 0}]},
    })
    assert response.status_code == 502
    result = response.get_json()
    assert result["ok"] is False
    assert result["result"]["assessment"] == "incomplete"
    assert result["result"]["validation_log"]["model_reviewed"] is False
