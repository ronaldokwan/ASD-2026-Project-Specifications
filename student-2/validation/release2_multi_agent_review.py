#!/usr/bin/env python3
"""Generate reproducible Student 2 Multi-Agent Workflow Review evidence.

The workflow must already have a recorded Human Review decision. The script
retrieves the complete workflow through the Student 2 Backend/API, verifies
that the shared completion gate survived the integration boundary, filters
the shared coordination audit log to the selected workflow, and sends the
workflow to AI-Mode's multi_agent_workflow review mode.

Example:
    python student-2/validation/release2_multi_agent_review.py \
        --order-id 33 --workflow-id <workflow-id> --name accepted-ui-run
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "docs" / "evidence" / "student-2" / "release-2"
BACKEND_URL = os.getenv("STUDENT2_BACKEND_URL", "http://localhost:8002").rstrip("/")
AI_MODE_URL = os.getenv("AI_MODE_URL", "http://localhost:7001").rstrip("/")
AUDIT_LOG = Path(os.getenv(
    "MULTI_AGENT_AUDIT_LOG",
    str(ROOT / "reports" / "multi-agent" / "coordination_audit.jsonl"),
))

REQUIRED_GATE_FIELDS = (
    "planner_completed",
    "worker_completed",
    "reviewer_completed",
    "human_decision_recorded",
)


def save(path: Path, body: object, *, json_lines: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if json_lines:
        content = "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in body)
    else:
        content = json.dumps(body, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")
    print("saved", path.relative_to(ROOT))


def fetch_workflow(order_id: int, workflow_id: str) -> dict:
    response = requests.get(
        f"{BACKEND_URL}/api/orders/{order_id}/multi-agent/{workflow_id}",
        timeout=30,
    )
    response.raise_for_status()
    workflow = response.json()
    gate = workflow.get("completion_gate")
    if not isinstance(gate, dict):
        raise RuntimeError("Backend/API response is missing completion_gate")
    missing = [field for field in REQUIRED_GATE_FIELDS if field not in gate]
    if missing:
        raise RuntimeError("completion_gate is missing: " + ", ".join(missing))
    if not all(gate.get(field) for field in REQUIRED_GATE_FIELDS):
        raise RuntimeError("workflow must complete all model stages and Human Review before evidence capture")
    return workflow


def audit_events(workflow_id: str) -> list[dict]:
    if not AUDIT_LOG.exists():
        raise RuntimeError(f"coordination audit log not found: {AUDIT_LOG}")
    events = []
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("workflow_id") == workflow_id:
            events.append(event)
    if not events:
        raise RuntimeError("no coordination audit events found for workflow " + workflow_id)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", type=int, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--name", default="multi-agent-run")
    args = parser.parse_args()

    output = EVIDENCE_ROOT / args.name
    workflow = fetch_workflow(args.order_id, args.workflow_id)
    events = audit_events(args.workflow_id)
    subject = {"mode": "multi_agent_workflow", "subject": {"workflow": workflow}}

    save(output / "multi-agent-workflow.json", workflow)
    save(output / "coordination-audit-log.jsonl", events, json_lines=True)
    save(output / "multi-agent-review-subject.json", subject)

    response = requests.post(
        AI_MODE_URL + "/agent/validate",
        json=subject,
        timeout=600,
    )
    response.raise_for_status()
    review = response.json()
    save(output / "multi-agent-review-review.json", review)

    validation = (review.get("result") or {}).get("validation_log") or {}
    print("workflow_status:", workflow.get("status"))
    print("audit_events:", len(events))
    print("review_status:", review.get("status"))
    print("assessment:", (review.get("result") or {}).get("assessment"))
    print("evidence_gate:", validation.get("evidence_gate"))


if __name__ == "__main__":
    main()
