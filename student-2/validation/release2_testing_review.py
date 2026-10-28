#!/usr/bin/env python3
"""Generate Student 2 local and hosted Testing Review evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "student-2" / "release-2"
PRE_COMMIT_LOG = EVIDENCE / "01-pre-commit-security-scans.log"
ENDPOINT_TEST = ROOT / "student-2" / "endpoint-tests" / "test_live_order_endpoints.py"
AI_MODE_URL = "http://localhost:7001"
RUN_ID = "40673632219"
RUN_COMMIT = "70ba5bf"


def save(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print("saved", path.relative_to(ROOT))


def security_results() -> list[dict]:
    text = PRE_COMMIT_LOG.read_text(encoding="utf-8")
    hooks = (
        ("ruff-security", "Ruff security rules"),
        ("detect-secrets", "detect-secrets staged-file scan"),
        ("pip-audit", "pip-audit relevant Python requirements"),
    )
    results = []
    for hook_id, label in hooks:
        matched = re.search(re.escape(label) + r"\.*\s*(Passed|Failed|Skipped)", text)
        status = (matched.group(1).lower() if matched else "not_run")
        results.append({
            "name": hook_id,
            "status": status,
            "phase": "pre_commit",
            "source": PRE_COMMIT_LOG.name,
        })
    return results


def endpoint_results(phase: str, status: str) -> list[dict]:
    return [
        {
            "endpoint": "get_order",
            "route": "GET /api/orders/{id}",
            "test_ref": "student-2/endpoint-tests/test_live_order_endpoints.py",
            "phase": phase,
            "status": status,
            "tests": 1 if status == "passed" else 0,
            "passed": 1 if status == "passed" else 0,
        },
        {
            "endpoint": "update_order_status",
            "route": "PATCH /api/orders/{id}/status",
            "test_ref": "student-2/endpoint-tests/test_live_order_endpoints.py",
            "phase": phase,
            "status": status,
            "tests": 2 if status == "passed" else 0,
            "passed": 2 if status == "passed" else 0,
        },
    ]


def review(name: str, subject: dict) -> dict:
    directory = EVIDENCE / name
    save(directory / "testing-review-subject.json", {
        "mode": "testing_report",
        "subject": subject,
    })
    response = requests.post(
        AI_MODE_URL + "/agent/validate",
        json={"mode": "testing_report", "subject": subject},
        timeout=600,
    )
    response.raise_for_status()
    outcome = response.json()
    hosted_ci = subject.get("hosted_ci") if isinstance(subject.get("hosted_ci"), dict) else {}
    outcome["evidence_reference"] = {
        "github_actions_workflow": hosted_ci.get("workflow"),
        "github_actions_run_id": hosted_ci.get("run_id"),
        "github_actions_status": hosted_ci.get("status"),
        "github_actions_commit": hosted_ci.get("commit"),
    }
    save(directory / "testing-review-review.json", outcome)
    log = (outcome.get("result") or {}).get("validation_log") or {}
    print(
        name,
        "gate=" + str(log.get("evidence_assessment")),
        "model=" + str(log.get("model_assessment")),
        "result=" + str(log.get("authoritative_assessment")),
    )
    return outcome


def main() -> None:
    common = {
        "student": 2,
        "feature": "Customer Orders",
        "test_code": ENDPOINT_TEST.read_text(encoding="utf-8"),
        "pre_commit_security_results": security_results(),
    }
    review(
        "testing-review-local",
        {
            **common,
            "execution_results": (
                "The security hooks were executed locally. The backend endpoint checks were not "
                "run as post-commit tests, and no hosted GitHub Actions run is supplied."
            ),
            "post_commit_backend_endpoint_tests": endpoint_results("local", "not_run"),
            "hosted_ci": {"workflow": "student-2.yml", "run_id": None, "status": "not_run"},
        },
    )
    hosted = review(
        "testing-review-ci",
        {
            **common,
            "execution_results": (
                "Hosted GitHub Actions run 40673632219 passed on commit 70ba5bf. The workflow "
                "started and health-checked the live Student 2 containers, then passed three "
                "post-commit HTTP checks: GET order, PATCH valid status, and PATCH invalid status "
                "returning HTTP 400 without changing the order."
            ),
            "post_commit_backend_endpoint_tests": endpoint_results("post_commit", "passed"),
            "hosted_ci": {
                "workflow": "student-2.yml",
                "run_id": RUN_ID,
                "commit": RUN_COMMIT,
                "status": "passed",
            },
        },
    )
    # Retain the original report reference while storing the full native response.
    save(EVIDENCE / "03-testing-review.json", hosted)


if __name__ == "__main__":
    main()
