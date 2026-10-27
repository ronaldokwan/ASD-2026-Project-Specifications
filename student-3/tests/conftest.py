"""Fixtures for the three Student 3 microservices."""

import importlib.util
import os
import sys
import tempfile

import pytest

STUDENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(STUDENT_DIR, "backend")
DATABASE_DIR = os.path.join(STUDENT_DIR, "database")
FRONTEND_DIR = os.path.join(STUDENT_DIR, "frontend")

for path in (FRONTEND_DIR, DATABASE_DIR, BACKEND_DIR):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="asd-student3-"), "customers.db")
os.environ["DB_PATH"] = TEST_DB_PATH


def _load(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


import db as db_module  # noqa: E402

db_service = _load("student3_db_service", os.path.join(DATABASE_DIR, "app.py"))


@pytest.fixture()
def database():
    db_module.init_db(force_reseed=True)
    return db_module


@pytest.fixture()
def db_http(database):
    db_service.app.config.update(TESTING=True)
    return db_service.app.test_client()


from app import create_app  # noqa: E402
from app import db_client as backend_db  # noqa: E402


@pytest.fixture()
def backend():
    application = create_app()
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def fake_db(monkeypatch):
    class FakeDatabase:
        def __init__(self):
            self.rows = {
                1: {"id": 1, "name": "Avery Brooks", "email": "avery@example.test",
                    "phone": "0400 000 001", "address": "Sydney NSW",
                    "loyalty_tier": "Silver", "joined_at": "2025-01-10"},
                2: {"id": 2, "name": "Jordan Chen", "email": "jordan@example.test",
                    "phone": None, "address": None,
                    "loyalty_tier": "Bronze", "joined_at": "2026-02-20"},
            }
            self.next_id = 3

        def list_customers(self, search=None):
            rows = list(self.rows.values())
            if search:
                term = search.lower()
                rows = [row for row in rows if term in row["name"].lower()
                        or term in row["email"].lower()]
            return rows

        def get_customer(self, customer_id):
            if customer_id not in self.rows:
                raise backend_db.NotFound("customer {} does not exist".format(customer_id))
            return self.rows[customer_id]

        def create_customer(self, payload):
            if any(row["email"].lower() == payload["email"].lower()
                   for row in self.rows.values()):
                raise backend_db.Conflict("email already exists")
            row = dict(payload, id=self.next_id)
            self.rows[self.next_id] = row
            self.next_id += 1
            return row

        def update_customer(self, customer_id, payload):
            row = self.get_customer(customer_id)
            row.update(payload)
            return row

        def delete_customer(self, customer_id):
            self.get_customer(customer_id)
            del self.rows[customer_id]
            return {"deleted": customer_id}

        def health(self):
            return {"service": "student-3-db", "status": "ok", "customers": len(self.rows)}

    fake = FakeDatabase()
    for name in ("list_customers", "get_customer", "create_customer", "update_customer",
                 "delete_customer", "health"):
        monkeypatch.setattr(backend_db, name, getattr(fake, name))
    return fake


frontend_service = _load("student3_frontend", os.path.join(FRONTEND_DIR, "app.py"))
import api_client as frontend_api  # noqa: E402


@pytest.fixture()
def frontend():
    frontend_service.app.config.update(TESTING=True)
    return frontend_service.app.test_client()


@pytest.fixture()
def fake_api(monkeypatch):
    state = {
        "customers": [{"id": 1, "name": "Avery Brooks", "email": "avery@example.test",
                       "phone": "0400 000 001", "address": "Sydney NSW",
                       "loyalty_tier": "Silver", "joined_at": "2025-01-10"}],
        "created": [],
        "deleted": [],
        "multi_agent_reviews": [],
    }

    def list_customers(search=None):
        if search and search.lower() not in "avery brooks avery@example.test":
            return []
        return state["customers"]

    def create(payload):
        state["created"].append(payload)
        return dict(payload, id=9)

    monkeypatch.setattr(frontend_api, "list_customers", list_customers)
    monkeypatch.setattr(frontend_api, "get_customer", lambda customer_id: state["customers"][0])
    monkeypatch.setattr(frontend_api, "create_customer", create)
    monkeypatch.setattr(frontend_api, "update_customer",
                        lambda customer_id, payload: dict(payload, id=customer_id))
    monkeypatch.setattr(frontend_api, "delete_customer",
                        lambda customer_id: state["deleted"].append(customer_id))
    monkeypatch.setattr(frontend_api, "suggest_reward", lambda customer_id: {
        "ok": True,
        "result": {"reward": "10% off the next purchase",
                   "reason": "A suitable reward for this returning Silver-tier customer."},
        "attempts": 1,
        "fallback_used": False,
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 100,
        "trace": [{"step": "Plan", "detail": "Used stored customer facts."}],
        "grounding": {"customer_name": "Avery Brooks", "loyalty_tier": "Silver",
                      "joined_at": "2025-01-10"},
    })
    monkeypatch.setattr(frontend_api, "check_customer_profile", lambda customer_id: {
        "tool": "check_customer_profile", "tier_valid": True,
        "membership_days": 629, "profile_status": "complete",
        "missing_optional_fields": [], "warnings": [], "errors": [],
    })
    monkeypatch.setattr(frontend_api, "ask_loyalty_benefits", lambda question: {
        "status": "ok",
        "answer": "Gold customers may receive fifteen percent off the next purchase.",
        "sources": [{
            "source": "customer-loyalty-policy.md",
            "section": "Gold Membership",
            "snippet": "Gold customers may receive either fifteen percent off...",
        }],
        "confidence": "high",
    })
    workflow = {
        "workflow_id": "workflow-123", "subject_ref": "student-3-customer:1",
        "status": "human_review", "stage": "human_review", "created_at": "2026-10-22T00:00:00+00:00",
        "plan": {"model_generated": {"tasks": [{"task": "Check policy", "evidence_refs": ["policy"]}]},
                 "application_enforced": {"acceptance_criteria": ["Cite policy"],
                                          "constraints": ["Do not apply reward"]}},
        "worker_result": {"recommendation": "Review benefit.", "rationale": "Policy evidence supports review.",
                           "policy_basis": "Silver Membership.", "evidence_refs": ["policy"]},
        "reviewer_result": {"action": "ready_for_human", "findings": [],
                             "missing_information": [], "recommendations": []},
        "evidence": [{"id": "policy", "source": "RAG", "status": "available", "content": "Policy snippet."}],
        "roles": [{"role": "planner", "model": "stub-model"}],
        "revision_count": 0, "max_revisions": 1,
        "completion_gate": {"planner_completed": True, "worker_completed": True,
                             "reviewer_completed": True, "human_decision_recorded": False},
    }
    monkeypatch.setattr(frontend_api, "start_multi_agent_review", lambda customer_id: {
        "workflow_id": "workflow-123", "status": "queued",
    })
    monkeypatch.setattr(frontend_api, "get_multi_agent_workflow", lambda customer_id, workflow_id: workflow)
    monkeypatch.setattr(frontend_api, "list_multi_agent_workflows", lambda customer_id: {
        "count": 1, "workflows": [workflow],
    })

    def review(customer_id, workflow_id, payload):
        state["multi_agent_reviews"].append(payload)
        return dict(workflow, status={"accept": "accepted", "partial_accept": "partially_accepted",
                                      "reject": "rejected"}[payload["decision"]],
                    human_decision=payload)

    monkeypatch.setattr(frontend_api, "review_multi_agent_workflow", review)
    return state
