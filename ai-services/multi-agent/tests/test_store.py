"""Unit tests for the Multi-Agent workflow history / audit log.

Run from the repository root: pytest ai-services/multi-agent/tests -v
"""

import json
import os
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from agent import store  # noqa: E402


def test_create_then_human_review_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "workflow_log.jsonl"))
    store._WORKFLOWS.clear()
    store._ORDER.clear()

    created = store.create("wf1", {
        "status": "pending_human_review",
        "worker": {"result": {"summary": "restock soon"}},
    })
    assert created["workflow_id"] == "wf1"
    assert store.get("wf1")["status"] == "pending_human_review"

    updated = store.update_human_review(
        "wf1",
        {"decision": "approve", "comment": "looks fine", "reviewer": "alex"},
        {"summary": "restock soon"},
        "approved",
    )
    assert updated["status"] == "approved"
    assert updated["human_review"]["decision"] == "approve"
    assert store.get("wf1")["status"] == "approved"


def test_list_recent_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "workflow_log.jsonl"))
    store._WORKFLOWS.clear()
    store._ORDER.clear()

    store.create("wf1", {"status": "pending_human_review"})
    store.create("wf2", {"status": "pending_human_review"})

    recent = store.list_recent()
    assert [record["workflow_id"] for record in recent] == ["wf2", "wf1"]


def test_update_human_review_on_unknown_workflow_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "LOG_PATH", str(tmp_path / "workflow_log.jsonl"))
    store._WORKFLOWS.clear()
    store._ORDER.clear()

    assert store.update_human_review("missing", {}, {}, "approved") is None


def test_audit_log_records_every_state_change(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    log_path = tmp_path / "workflow_log.jsonl"
    monkeypatch.setattr(store, "LOG_PATH", str(log_path))
    store._WORKFLOWS.clear()
    store._ORDER.clear()

    store.create("wf1", {"status": "pending_human_review"})
    store.update_human_review("wf1", {"decision": "reject"}, None, "rejected")

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["workflow_run", "human_review"]
