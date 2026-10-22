"""Workflow history for the Multi-Agent Server.

Keeps completed Planner -> Worker -> Reviewer -> Human Review records in
memory for the life of the process, and appends every state change to
``data/workflow_log.jsonl`` as a durable, human-readable audit trail - this is
the "coordination/audit logs" evidence the technical report asks for.
"""

import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LOG_PATH = os.path.join(DATA_DIR, "workflow_log.jsonl")

_WORKFLOWS = {}
_ORDER = []


def _append_log(event):
    os.makedirs(DATA_DIR, exist_ok=True)
    event = dict(event, logged_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def create(workflow_id, record):
    """Store a freshly-run Planner/Worker/Reviewer outcome, awaiting human review."""
    record = dict(record)
    record["workflow_id"] = workflow_id
    record["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _WORKFLOWS[workflow_id] = record
    _ORDER.append(workflow_id)
    _append_log({"event": "workflow_run", "workflow_id": workflow_id, "record": record})
    return record


def get(workflow_id):
    return _WORKFLOWS.get(workflow_id)


def update_human_review(workflow_id, human_review, final_result, status):
    """Attach the human decision to a workflow and return the updated record."""
    record = _WORKFLOWS.get(workflow_id)
    if record is None:
        return None
    record["human_review"] = human_review
    record["final_result"] = final_result
    record["status"] = status
    record["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _append_log(
        {
            "event": "human_review",
            "workflow_id": workflow_id,
            "human_review": human_review,
            "status": status,
        }
    )
    return record


def list_recent(limit=50):
    ids = list(reversed(_ORDER))[:limit]
    return [_WORKFLOWS[i] for i in ids]
