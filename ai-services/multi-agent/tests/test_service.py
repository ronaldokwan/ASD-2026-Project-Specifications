"""Isolated orchestration and human-review tests; no Ollama calls are made."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import service


class ImmediateExecutor:
    def submit(self, function, workflow_id):
        function(workflow_id)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "HISTORY_PATH", tmp_path / "workflow_history.jsonl")
    monkeypatch.setattr(service, "AUDIT_PATH", tmp_path / "coordination_audit.jsonl")
    monkeypatch.setattr(service, "_executor", ImmediateExecutor())
    return service.create_app().test_client()


def _output_for(role, action="ready_for_human"):
    if role == "planner":
        return {
            "tasks": [{"task": "Compare customer tier to policy", "evidence_refs": ["facts", "policy"]}],
        }
    if role == "worker":
        return {
            "recommendation": "Offer the Silver-tier delivery benefit.",
            "rationale": "The supplied policy lists this benefit for Silver members.",
            "policy_basis": "policy",
            "evidence_refs": ["facts", "policy"],
        }
    return {
        "action": action,
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [{"severity": "low", "finding": "The result cites the supplied policy.",
                      "evidence_ref": "policy", "classification": "other", "claim_field": "multiple"}],
        "missing_information": [],
        "recommendations": ["Administrator should review before use."],
    }


def _reviewer_output(output, *args, **kwargs):
    """Keep legacy-preservation unit cases valid under the required reviewer schema."""
    output = dict(output)
    output.setdefault("claim_assessment", {
        "recommendation": "supported", "rationale": "supported", "consistency": "consistent",
    })
    for finding in output.get("findings", []):
        finding.setdefault("classification", "other")
        finding.setdefault("claim_field", "multiple")
    return service._reviewer_output(output, *args, **kwargs)


def _start(client, max_revisions=1):
    return client.post("/workflow", json={
        "subject_ref": "student-3-customer:7",
        "request": {"goal": "loyalty recommendation", "loyalty_tier": "Silver"},
        "evidence": [
            {"id": "facts", "source": "customer-api", "status": "available", "content": "Tier Silver; joined 2025-01-10."},
            {"id": "policy", "source": "rag", "status": "available", "content": "Silver members may receive delivery benefit."},
        ],
        "max_revisions": max_revisions,
    })


def test_planner_worker_reviewer_handoff_and_human_acceptance(client, monkeypatch):
    calls = []

    def fake_call(role, _prompt):
        calls.append(role)
        return "qwen2.5:0.5b", _output_for(role)

    monkeypatch.setattr(service, "_call_model", fake_call)
    response = _start(client)
    assert response.status_code == 202
    workflow_id = response.get_json()["workflow_id"]
    workflow = client.get("/workflow/status/" + workflow_id).get_json()

    assert calls == ["planner", "worker", "reviewer"]
    assert workflow["status"] == "human_review"
    assert workflow["completion_gate"]["human_decision_recorded"] is False
    assert [item["role"] for item in workflow["roles"]] == calls

    accepted = client.post("/workflow/{}/review".format(workflow_id), json={"decision": "accept"})
    assert accepted.status_code == 200
    assert accepted.get_json()["status"] == "accepted"
    assert accepted.get_json()["completion_gate"]["human_decision_recorded"] is True
    assert client.get("/workflow/history?subject_ref=student-3-customer:7").get_json()["count"] == 1
    assert (service.AUDIT_PATH.read_text().count("human_decision_recorded")) == 1


def test_invalid_reviewer_output_uses_one_bounded_validation_retry(client, monkeypatch):
    reviewer_calls = []
    invalid = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "unsupported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    valid = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }

    def call_model(role, prompt):
        if role == "reviewer":
            reviewer_calls.append(prompt)
            return "deepseek-r1:8b", invalid if len(reviewer_calls) == 1 else valid
        return "model", _output_for(role)

    monkeypatch.setattr(service, "_call_model", call_model)
    workflow_id = _start(client).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    assert workflow["status"] == "human_review"
    assert len(reviewer_calls) == 2
    assert "APPLICATION VALIDATION FEEDBACK" in reviewer_calls[1]
    assert workflow["reviewer_validation_retries"] == 1
    assert workflow["reviewer_validation_log"][0]["error"].startswith("Reviewer action conflicts")
    assert [role["validation_status"] for role in workflow["roles"] if role["role"] == "reviewer"] == [
        "failed", "passed",
    ]
    assert workflow["reviewer_result"]["action"] == "ready_for_human"


def test_reviewer_remains_failed_after_bounded_validation_retry(client, monkeypatch):
    invalid = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "unsupported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: (
        "deepseek-r1:8b" if role == "reviewer" else "model",
        invalid if role == "reviewer" else _output_for(role),
    ))

    workflow_id = _start(client, max_revisions=1).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    assert workflow["status"] == "failed"
    assert workflow["completion_gate"]["reviewer_completed"] is False
    assert workflow["completion_gate"]["human_decision_recorded"] is False
    assert workflow["reviewer_result"] is None
    assert [attempt["output"] for attempt in workflow["reviewer_validation_log"]] == [invalid, invalid]
    failures = [json.loads(line) for line in service.AUDIT_PATH.read_text().splitlines()
                if json.loads(line)["event"] == "reviewer_validation_failed"]
    assert [failure["details"]["output"] for failure in failures] == [invalid, invalid]
    assert "remained invalid after the configured retry" in workflow["failure"]
    assert client.post("/workflow/{}/review".format(workflow_id), json={"decision": "accept"}).status_code == 409


def test_reviewer_call_failure_retains_elapsed_time_and_diagnostic_context(client, monkeypatch):
    def call_model(role, _prompt):
        if role == "reviewer":
            raise service.requests.Timeout("reviewer timed out")
        return "model", _output_for(role)

    monkeypatch.setattr(service, "_call_model", call_model)
    workflow_id = _start(client).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()
    attempt = workflow["reviewer_validation_log"][0]

    assert workflow["status"] == "failed"
    assert attempt["output"] is None
    assert attempt["error"] == "reviewer timed out"
    assert attempt["elapsed_seconds"] >= 0
    assert attempt["prompt_characters"] > 0
    assert attempt["model"] == service.ROLE_MODELS["reviewer"]
    assert workflow["roles"][-1]["validation_status"] == "call_failed"
    events = [json.loads(line) for line in service.AUDIT_PATH.read_text().splitlines()]
    assert any(event["event"] == "reviewer_call_failed" and
               event["details"]["elapsed_seconds"] == attempt["elapsed_seconds"]
               for event in events)


def test_reviewer_consistency_schema_requires_classifying_present_fields():
    prompt = service._prompt("reviewer", {"goal": "Review."}, _loyalty_evidence("Gold"),
                             worker={"recommendation": "A", "rationale": "B"})
    schema = service._model_output_schema("reviewer", prompt)
    enum = service.CONSISTENCY_SCHEMA["properties"]["consistency_check"]["properties"]["assessment"]["enum"]
    assert "not_applicable" not in enum
    assert "findings" not in schema["properties"]
    assert "policy_basis" not in prompt.partition("WORKER RESULT:\n")[2]
    assert "correctly rejected unapproved proposal" in service.ROLE_INSTRUCTIONS["reviewer"]

    output = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "not_applicable",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    with pytest.raises(service.WorkflowError, match="claim_assessment"):
        service._reviewer_output(output, _loyalty_evidence("Gold"))


def test_reviewer_distinguishes_endorsed_unsupported_benefit_from_rejected_proposal():
    evidence = _loyalty_evidence("Gold")
    evidence.append({
        "id": "candidate_recommendation", "source": "test proposal", "status": "available",
        "content": "Gold customers may receive a 99% discount.",
        "meaning": "Unapproved proposal only; it is not an endorsed benefit.",
    })
    proposed = "Gold customers may receive a 99% discount on the next purchase."
    endorsed_worker = {
        "recommendation": proposed,
        "rationale": "The customer is Gold.",
        "policy_basis": "loyalty_policy",
    }
    unsupported = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "unsupported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [{
            "severity": "high", "finding": "The policy does not approve the 99% discount.",
            "evidence_ref": "loyalty_policy", "classification": "unsupported_claim",
            "claim_field": "recommendation", "claim_quote": proposed, "conflicting_claims": None,
        }],
        "missing_information": [], "recommendations": [],
    }
    accepted = service._reviewer_output(unsupported, evidence, endorsed_worker)
    assert accepted["action"] == "not_supported"
    assert accepted["findings"][0]["claim_quote"] == proposed

    unsupported["findings"][0]["claim_quote"] = evidence[-1]["content"]
    with pytest.raises(service.WorkflowError, match="quote the actual unsupported Worker field"):
        service._reviewer_output(unsupported, evidence, endorsed_worker)

    rejected_worker = {
        "recommendation": "The proposed 99% discount is unsupported. Gold customers may receive fifteen percent off the next purchase.",
        "rationale": "The policy permits fifteen percent, not 99%.",
        "policy_basis": "loyalty_policy",
    }
    correct_rejection = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    result = service._reviewer_output(correct_rejection, evidence, rejected_worker)
    assert result["action"] == "ready_for_human"
    assert result["findings"] == []


@pytest.mark.parametrize("decision", ["partial_accept", "reject"])
def test_human_partial_acceptance_and_rejection_are_saved(client, monkeypatch, decision):
    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: ("model", _output_for(role)))
    workflow_id = _start(client).get_json()["workflow_id"]
    if decision == "partial_accept":
        payload = {
            "decision": decision,
            "feedback": "Correct the reason to mention the evidence limit.",
            "corrected_output": {"recommendation": "Retain the proposed benefit.", "rationale": "Policy evidence is limited."},
            "accepted_fields": ["recommendation"],
            "unresolved_issues": ["Confirm benefit eligibility before applying."],
        }
        expected = "partially_accepted"
    else:
        payload = {"decision": decision, "feedback": "The evidence is insufficient.", "unresolved_issues": ["No eligibility confirmation."]}
        expected = "rejected"
    response = client.post("/workflow/{}/review".format(workflow_id), json=payload)
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == expected
    assert result["human_decision"]["feedback"] == payload["feedback"]

    retry = client.post("/workflow/{}/review".format(workflow_id), json={
        "decision": "reject", "feedback": "Attempt to overwrite the saved decision.",
    })
    assert retry.status_code == 409
    saved = client.get("/workflow/" + workflow_id).get_json()
    assert saved["human_decision"]["decision"] == decision
    if decision == "partial_accept":
        assert saved["human_decision"]["corrected_output"] == payload["corrected_output"]
    assert service.AUDIT_PATH.read_text().count('"event":"human_decision_recorded"') == 1


def test_partial_accept_without_feedback_is_rejected_without_saving(client, monkeypatch):
    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: ("model", _output_for(role)))
    workflow_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    response = client.post("/workflow/{}/review".format(workflow_id), json={
        "decision": "partial_accept",
        "feedback": "",
        "corrected_output": {"recommendation": "Corrected recommendation.", "rationale": "Informational only."},
        "accepted_fields": ["Bronze tier", "Approved Bronze benefits"],
        "unresolved_issues": ["None for this wording correction"],
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "Feedback is required for partial acceptance."
    saved = client.get("/workflow/" + workflow_id).get_json()
    assert saved["status"] == "human_review"
    assert saved["human_decision"] is None
    assert "human_decision_recorded" not in service.AUDIT_PATH.read_text()


def test_bounded_revision_and_malformed_output_fail_honestly(client, monkeypatch):
    calls = []

    def revise_once(role, _prompt):
        calls.append(role)
        return "model", _output_for(role, "revise")

    monkeypatch.setattr(service, "_call_model", revise_once)
    workflow_id = _start(client, max_revisions=1).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()
    assert calls == ["planner", "worker", "reviewer", "worker", "reviewer"]
    assert workflow["revision_count"] == 1
    assert workflow["status"] == "human_review"

    monkeypatch.setattr(service, "_call_model", lambda _role, _prompt: ("model", {"bad": True}))
    failed_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    failed = client.get("/workflow/" + failed_id).get_json()
    assert failed["status"] == "failed"
    assert "Planner tasks" in failed["failure"]
    assert client.post("/workflow/{}/review".format(failed_id), json={"decision": "accept"}).status_code == 409


def test_incomplete_plan_cannot_pass_the_completion_gate(client, monkeypatch):
    calls = []

    def fake_call(role, _prompt):
        calls.append(role)
        return "test-model", _output_for(role)

    def incomplete_plan(_output, _evidence_ids, request_data):
        contract = request_data.get("plan_contract", {})
        return {
            "model_generated": {"tasks": []},
            "application_enforced": {
                "acceptance_criteria": contract.get("acceptance_criteria", []),
                "constraints": contract.get("constraints", []),
            },
        }

    monkeypatch.setattr(service, "_call_model", fake_call)
    monkeypatch.setattr(service, "_planner_output", incomplete_plan)
    workflow_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    assert calls == ["planner"]
    assert workflow["status"] == "failed"
    assert "complete required plan" in workflow["failure"]
    assert workflow["completion_gate"]["planner_completed"] is False
    assert workflow["completion_gate"]["worker_completed"] is False
    assert workflow["completion_gate"]["reviewer_completed"] is False
    assert client.post("/workflow/{}/review".format(workflow_id), json={"decision": "accept"}).status_code == 409


def test_invalid_review_and_missing_models_do_not_complete(client, monkeypatch):
    monkeypatch.setattr(service, "_call_model", lambda _role, _prompt: (_ for _ in ()).throw(
        service.WorkflowError("configured planner model is unavailable")
    ))
    workflow_id = _start(client).get_json()["workflow_id"]
    failed = client.get("/workflow/" + workflow_id).get_json()
    assert failed["status"] == "failed"
    assert failed["completion_gate"]["human_decision_recorded"] is False
    assert client.post("/workflow/{}/review".format(workflow_id), json={"decision": "partial_accept"}).status_code == 409

    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: ("model", _output_for(role)))
    ready_id = _start(client).get_json()["workflow_id"]
    invalid = client.post("/workflow/{}/review".format(ready_id), json={"decision": "partial_accept"})
    assert invalid.status_code == 400
    assert client.get("/workflow/" + ready_id).get_json()["status"] == "human_review"


def test_each_model_role_uses_its_configured_model_and_output_schema(monkeypatch):
    role_models = {"planner": "planner-local", "worker": "worker-local", "reviewer": "reviewer-local"}
    monkeypatch.setattr(service, "ROLE_MODELS", role_models)
    monkeypatch.setattr(service, "_available_models", lambda **_kwargs: list(role_models.values()))
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    def post(url, json, timeout):
        calls.append({"url": url, "payload": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(service.requests, "post", post)
    evidence = [{"id": "synthetic_id", "source": "fixture", "status": "available", "content": "synthetic"}]
    prompts = {role: service._prompt(role, {"goal": "synthetic"}, evidence)
               for role in ("planner", "worker", "reviewer")}
    for role, prompt in prompts.items():
        _model, output = service._generate_model(role, prompt)
        assert output == {}

    assert [call["payload"]["model"] for call in calls] == list(role_models.values())
    assert [call["payload"]["format"] for call in calls] == [
        service._model_output_schema(role, prompts[role]) for role in role_models
    ]
    def constrained_ids(role, schema):
        if role == "planner":
            return schema["properties"]["tasks"]["items"]["properties"]["evidence_refs"]["items"]["enum"]
        if role == "worker":
            return schema["properties"]["evidence_refs"]["items"]["enum"]
        return schema["properties"]["support_checks"]["properties"]["recommendation"]["properties"]["evidence_refs"]["items"]["enum"]

    assert all("synthetic_id" in constrained_ids(role, call["payload"]["format"])
               for call, role in zip(calls, role_models))
    assert calls[1]["payload"]["format"]["properties"]["policy_basis"]["enum"] == ["synthetic_id"]
    assert calls[0]["payload"]["format"]["properties"]["tasks"]["items"]["properties"]["evidence_refs"]["maxItems"] == 1
    assert calls[1]["payload"]["format"]["properties"]["evidence_refs"]["maxItems"] == 1
    assert all(call["payload"]["options"]["num_predict"] == service.NUM_PREDICT for call in calls)
    assert all(call["payload"]["options"]["num_ctx"] >= 4096 for call in calls)
    assert "think" not in calls[0]["payload"]
    assert "think" not in calls[1]["payload"]
    assert calls[2]["payload"]["think"] is False
    assert all(call["payload"]["system"] == service.ROLE_INSTRUCTIONS[role]
               for call, role in zip(calls, role_models))


def _loyalty_evidence(tier="Gold", policy_status="available"):
    benefits = {
        "Bronze": "Bronze customers may receive either free standard delivery on the next purchase or five percent off the next purchase. These are the only approved Bronze loyalty benefits.",
        "Silver": "Silver customers may receive either ten percent off the next purchase or free express delivery on the next purchase. These are the only approved Silver loyalty benefits.",
        "Gold": "Gold customers may receive either fifteen percent off the next purchase or early access to the next seasonal sale. These are the only approved Gold loyalty benefits.",
    }
    return [
        {"id": "customer_facts", "source": "student-3-customer-api", "status": "available",
         "meaning": "Authoritative stored customer fields.",
         "content": json.dumps({"loyalty_tier": tier, "joined_at": "2025-02-03", "has_phone": True})},
        {"id": "mcp_profile", "source": "shared-mcp-check_customer_profile", "status": "available",
         "meaning": "Profile completeness and tier validity only; not reward policy.",
         "content": json.dumps({"profile_status": "complete", "tier_valid": True})},
        {"id": "loyalty_policy", "source": "shared-rag-customer-loyalty-policy", "status": policy_status,
         "meaning": "Approved benefit policy for the matching tier.",
         "content": json.dumps({"status": "ok", "answer": benefits[tier],
                                 "sources": [{"section": tier + " Membership", "snippet": benefits[tier]}]})},
    ]


def test_planner_tasks_are_separate_from_application_enforced_requirements():
    contract = {
        "plan_contract": {
            "acceptance_criteria": ["Use the stored tier.", "Use only matching-tier policy benefits."],
            "constraints": ["Do not change the customer tier."],
        }
    }
    model_output = {
        "tasks": [{"task": "Read facts and policy", "evidence_refs": ["customer_facts", "loyalty_policy"]}],
    }
    plan = service._planner_output(model_output, {"customer_facts", "loyalty_policy"}, contract)
    assert plan["model_generated"]["tasks"] == model_output["tasks"]
    assert plan["application_enforced"]["acceptance_criteria"] == contract["plan_contract"]["acceptance_criteria"]
    assert plan["application_enforced"]["constraints"] == contract["plan_contract"]["constraints"]
    prompt = service._prompt("planner", {
        "goal": "Summarize approved benefits.",
        **contract,
        "worker_evidence_ids": ["customer_facts", "loyalty_policy"],
    }, _loyalty_evidence("Gold"))
    assert "Summarize approved benefits." in prompt
    assert "acceptance_criteria" not in prompt
    assert "Use the stored tier." not in prompt


def test_planner_must_cite_supplied_evidence_for_each_task():
    with pytest.raises(service.WorkflowError, match="referenced evidence"):
        service._planner_output({"tasks":[{"task":"Summarize the evidence.","evidence_refs":[]}]}, {"policy"})


def test_worker_preserves_model_citations_and_labels_application_added_sources():
    evidence = _loyalty_evidence("Silver")
    request_data = {
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_policy_evidence_ids": ["loyalty_policy"],
    }
    paraphrase = "Silver members may choose a ten percent saving on their next purchase or free express delivery for that purchase; these are the only approved benefits."
    result = service._worker_output({
        "recommendation": paraphrase, "rationale": "This paraphrases the matching-tier policy.",
        "policy_basis": "loyalty_policy", "evidence_refs": ["loyalty_policy", "customer_facts", "loyalty_policy"],
    }, {"customer_facts", "loyalty_policy"})
    checked = service._validate_worker_contract(result, evidence, request_data)
    assert checked["recommendation"] == paraphrase
    assert checked["evidence_refs"] == ["loyalty_policy", "customer_facts"]
    assert checked["application_added_evidence_refs"] == []

    omitted_tier_citation = dict(result, evidence_refs=["loyalty_policy"])
    checked = service._validate_worker_contract(omitted_tier_citation, evidence, request_data)
    assert checked["evidence_refs"] == ["loyalty_policy"]
    assert checked["application_added_evidence_refs"] == ["customer_facts"]

    unsupported = service._worker_output({
        "recommendation": "Silver customers get a 99% discount.", "rationale": "Unsupported claim.",
        "policy_basis": "loyalty_policy", "evidence_refs": ["customer_facts", "loyalty_policy"],
    }, {"customer_facts", "loyalty_policy"})
    checked_unsupported = service._validate_worker_contract(unsupported, evidence, request_data)
    assert checked_unsupported["recommendation"] == "Silver customers get a 99% discount."
    wrong_basis = dict(result, policy_basis="customer_facts")
    with pytest.raises(service.WorkflowError, match="policy_basis must cite"):
        service._validate_worker_contract(wrong_basis, evidence, request_data)

    appended_claim = dict(result, recommendation=paraphrase + " A bonus 99% discount is also approved.")
    assert service._validate_worker_contract(appended_claim, evidence, request_data)["recommendation"].endswith(
        "A bonus 99% discount is also approved."
    )


def test_worker_can_surface_unavailable_policy_without_citing_it_as_support():
    evidence = _loyalty_evidence("Bronze", policy_status="unavailable")
    request_data = {
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
    }
    result = service._worker_output({
        "recommendation": "No benefit recommendation can be made because policy evidence is unavailable.",
        "rationale": "The source status is unavailable.", "policy_basis": "customer_facts",
        "evidence_refs": ["customer_facts"],
    }, {"customer_facts"})
    assert service._validate_worker_contract(result, evidence, request_data)["application_added_evidence_refs"] == []


def test_role_prompts_preserve_source_meaning_and_limit_worker_support_sources():
    evidence = _loyalty_evidence("Gold")
    request_data = {"goal": "Summarize matching-tier policy benefits.",
                    "worker_evidence_ids": ["customer_facts", "loyalty_policy"],
                    "worker_policy_evidence_ids": ["loyalty_policy"]}
    worker_prompt = service._prompt("worker", request_data, evidence)
    reviewer_prompt = service._prompt("reviewer", request_data, evidence,
                                      plan={"tasks": []}, worker={"recommendation": "Example", "rationale": "Example reason"})
    assert '"mcp_profile"' not in worker_prompt
    permitted = worker_prompt.split("PERMITTED EVIDENCE IDS (copy exactly; never invent an ID):\n", 1)[1].split("\n\n", 1)[0]
    assert json.loads(permitted) == ["customer_facts", "loyalty_policy"]
    assert '"mcp_profile"' not in reviewer_prompt
    planner_prompt = service._prompt("planner", request_data, evidence)
    assert '"mcp_profile"' not in planner_prompt
    assert '"worker_evidence_ids": ["customer_facts", "loyalty_policy"]' in reviewer_prompt
    assert "not reward policy" in service.ROLE_INSTRUCTIONS["reviewer"]
    assert "application contract describes workflow instructions" in service.ROLE_INSTRUCTIONS["reviewer"]
    assert "preserve that qualification" in service.ROLE_INSTRUCTIONS["worker"]
    assert "when none exist, return an empty list" in service.REVIEWER_DECISION_INSTRUCTIONS
    assert "joined_at" in reviewer_prompt
    assert '"policy_evidence_ids": ["loyalty_policy"]' in worker_prompt
    assert "WORKER RESULT" in reviewer_prompt
    assert "include every ID listed in required_evidence_ids in evidence_refs" in service.ROLE_INSTRUCTIONS["worker"]


def test_role_schemas_allow_full_policy_quote_and_actionable_reviewer_finding():
    evidence = _loyalty_evidence("Bronze")
    worker_prompt = service._prompt("worker", {
        "goal": "Summarize policy.",
        "worker_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_policy_evidence_ids": ["loyalty_policy"],
    }, evidence)
    reviewer_prompt = service._prompt("reviewer", {"goal": "Review."}, evidence)
    worker_schema = service._model_output_schema("worker", worker_prompt)
    reviewer_schema = service._model_output_schema("reviewer", reviewer_prompt)
    assert worker_schema["properties"]["recommendation"]["maxLength"] >= len(
        json.loads(evidence[-1]["content"])["answer"]
    )
    assert worker_schema["properties"]["policy_basis"]["enum"] == ["loyalty_policy"]
    assert worker_schema["properties"]["recommendation"]["maxLength"] == 480
    assert worker_schema["properties"]["rationale"]["maxLength"] == 300
    assert reviewer_schema["properties"]["support_checks"]["properties"]["recommendation"]["properties"]["explanation"]["maxLength"] >= 300


def test_reviewer_output_is_preserved_for_human_review_without_application_rewriting():
    evidence = _loyalty_evidence("Gold")
    recommendation = "Gold customers may receive fifteen percent off the next purchase or early access to the next seasonal sale."
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [
            {"severity": "high", "finding": "The tier and approved benefits were not provided.", "evidence_ref": "customer_facts"},
            {"severity": "high", "finding": "The joining date is not provided.", "evidence_ref": "customer_facts"},
            {"severity": "high", "finding": "The loyalty policy does not establish the approved benefit options.", "evidence_ref": "loyalty_policy"},
        ],
        "missing_information": ["The joining date is not provided.", "The loyalty policy is not provided."],
        "recommendations": [recommendation, "The loyalty policy is not provided."],
    }, evidence, {"recommendation": recommendation, "rationale": "Policy-grounded.", "policy_basis": recommendation})
    assert result["action"] == "not_supported"
    assert result["missing_information"] == ["The joining date is not provided.", "The loyalty policy is not provided."]
    assert result["findings"][0]["finding"] == "The tier and approved benefits were not provided."
    assert result["recommendations"][-1] == "The loyalty policy is not provided."


def test_genuinely_unsupported_benefit_finding_is_preserved():
    evidence = _loyalty_evidence("Silver")
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high", "finding": "The claimed 99% discount is not supported by loyalty policy.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": [],
        "recommendations": ["Remove the unsupported 99% discount claim."],
    }, evidence, {"recommendation": "Silver customers may receive a 99% discount.",
                  "rationale": "The policy allows it.", "policy_basis": "99% discount"})
    assert result["action"] == "not_supported"
    assert result["findings"][0]["finding"].startswith("The claimed 99% discount")


def test_missing_policy_evidence_remains_a_real_negative_finding():
    evidence = _loyalty_evidence("Bronze", policy_status="insufficient")
    result = _reviewer_output({
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "evidence_unavailable", "rationale": "supported",
            "consistency": "consistent",
        },
        "findings": [],
        "missing_information": ["A benefit cannot be checked without the policy."],
        "recommendations": [],
    }, evidence, {"recommendation": "Consider a benefit.", "rationale": "Policy unavailable.", "policy_basis": "None"}, {
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_policy_evidence_ids": ["loyalty_policy"],
    })
    assert result["action"] == "not_supported"
    assert result["findings"] == []
    assert result["missing_information"] == ["A benefit cannot be checked without the policy."]
    assert result["application_added_findings"] == [{
        "source": "application", "severity": "high",
        "finding": "Required evidence loyalty_policy is insufficient and was not available to support the recommendation.",
        "evidence_ref": "loyalty_policy", "classification": "missing_evidence", "claim_field": "evidence",
    }]


def test_reviewer_negative_result_is_not_relabelled_as_approval():
    evidence = _loyalty_evidence("Silver")
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high", "finding": "Evidence does not establish the Silver benefits.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": ["Silver benefits are not provided."], "recommendations": [],
    }, evidence, {"recommendation": "Silver customers may receive ten percent off the next purchase or free express delivery.",
                  "rationale": "This is the policy option.", "policy_basis": "Silver Membership"})
    assert result["action"] == "not_supported"
    assert result["findings"][0]["finding"] == "Evidence does not establish the Silver benefits."
    assert "ready_for_human" not in result["action"]


def test_reviewer_instruction_regurgitation_is_preserved_for_human_review():
    evidence = _loyalty_evidence("Gold")
    instruction = "The worker should identify the tier recorded in customer_facts and use only matching policy."
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high", "finding": instruction, "evidence_ref": "customer_facts"}],
        "missing_information": [instruction], "recommendations": [instruction],
    }, evidence, {"recommendation": "A test result.", "rationale": "Test.", "policy_basis": "Test."})
    assert result["action"] == "not_supported"
    assert result["missing_information"] == [instruction]
    assert result["findings"][0]["finding"] == instruction
    assert result["recommendations"] == [instruction]


def test_reviewer_policy_claims_are_preserved_without_string_matching():
    evidence = _loyalty_evidence("Gold")
    quote = "Gold customers may receive either fifteen percent off the next purchase or early access to the next seasonal sale."
    finding = "The recommendation is not supported by evidence. The evidence states that {}".format(quote)
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high", "finding": finding, "evidence_ref": "loyalty_policy"}],
        "missing_information": ["Gold Membership"],
        "recommendations": [quote],
    }, evidence, {"recommendation": quote, "rationale": "From policy.", "policy_basis": quote})
    assert result["action"] == "not_supported"
    assert result["missing_information"] == ["Gold Membership"]
    assert result["findings"][0]["finding"] == finding


def test_reviewer_missing_policy_claim_is_preserved_for_human_assessment():
    evidence = _loyalty_evidence("Gold")
    recommendation = json.loads(evidence[-1]["content"])["answer"]
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high",
                      "finding": "The loyalty policy does not provide any details about Gold loyalty benefits.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": ["The Gold benefit details are not provided."],
        "recommendations": [],
    }, evidence, {"recommendation": recommendation, "rationale": "Policy-backed.", "policy_basis": recommendation})
    assert result["action"] == "not_supported"
    assert result["findings"][0]["finding"] == "The loyalty policy does not provide any details about Gold loyalty benefits."
    assert result["missing_information"] == ["The Gold benefit details are not provided."]


def test_reviewer_missing_information_is_not_inferred_from_phrase_matching():
    evidence = _loyalty_evidence("Gold")
    quote = json.loads(evidence[-1]["content"])["answer"]
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high", "finding": "The recommendation is unsupported.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": ["The loyalty policy provides specific benefit details for Gold members."],
        "recommendations": [],
    }, evidence, {"recommendation": quote, "rationale": "Policy-backed.", "policy_basis": quote})
    assert result["action"] == "not_supported"
    assert result["missing_information"] == ["The loyalty policy provides specific benefit details for Gold members."]


def test_reviewer_finding_is_not_rewritten_by_policy_phrase_matching():
    evidence = _loyalty_evidence("Gold")
    recommendation = json.loads(evidence[-1]["content"])["answer"]
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high",
                      "finding": "The loyalty policy does not explicitly state the approved benefits for Gold.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": ["The benefit is not sufficient in the supplied evidence."],
        "recommendations": [],
    }, evidence, {"recommendation": recommendation, "rationale": "Policy-backed.", "policy_basis": recommendation})
    assert result["action"] == "not_supported"
    assert result["findings"][0]["finding"] == "The loyalty policy does not explicitly state the approved benefits for Gold."


def test_reviewer_can_preserve_negative_policy_judgment_without_string_matching():
    evidence = _loyalty_evidence("Bronze")
    quote = json.loads(evidence[-1]["content"])["answer"]
    result = _reviewer_output({
        "action": "not_supported",
        "findings": [{"severity": "high",
                      "finding": "The requested benefit options are not supported by the evidence provided.",
                      "evidence_ref": "loyalty_policy"}],
        "missing_information": [quote],
        "recommendations": [],
    }, evidence, {"recommendation": quote, "rationale": "Policy-backed.", "policy_basis": quote})
    assert result["action"] == "not_supported"
    assert result["findings"][0]["finding"] == "The requested benefit options are not supported by the evidence provided."


def test_reviewer_contradictory_not_supported_output_fails_closed():
    evidence = _loyalty_evidence("Gold")
    output = {
        "action": "not_supported",
        "findings": [], "missing_information": [], "recommendations": ["ready_for_human"],
    }
    with pytest.raises(service.WorkflowError, match="without a concrete finding"):
        _reviewer_output(output, evidence, {"recommendation": "Supported by evidence."})
    output["findings"] = [{"severity": "low", "finding": "A problem was found.", "evidence_ref": "loyalty_policy"}]
    with pytest.raises(service.WorkflowError, match="action code in recommendations"):
        _reviewer_output(output, evidence, {"recommendation": "Supported by evidence."})


def test_reviewer_receives_full_evidence_and_contradiction_check_instructions():
    evidence = [
        {"id": "customer_facts", "source": "customer-api", "status": "available",
         "content": '{"loyalty_tier":"Silver"}',
         "meaning": "Authoritative for the stored tier only."},
        {"id": "loyalty_policy", "source": "customer-loyalty-policy.md", "status": "available",
         "content": "Silver customers may receive either ten percent off or free express delivery.",
         "meaning": "Authoritative for approved benefits."},
    ]
    worker = {
        "recommendation": "Recommend a 99% discount as approved.",
        "rationale": "The policy does not approve a 99% discount.",
        "policy_basis": "loyalty_policy",
        "evidence_refs": ["customer_facts", "loyalty_policy"],
    }

    prompt = service._prompt("reviewer", {"goal": "Review the recommendation."}, evidence,
                             {"model_generated": {"tasks": []}}, worker)
    assert "Silver customers may receive either ten percent off or free express delivery." in prompt
    assert "Recommend a 99% discount as approved." in prompt
    assert "The policy does not approve a 99% discount." in prompt
    assert "actual Worker recommendation and rationale with each other" in service.REVIEWER_CONSISTENCY_INSTRUCTIONS
    assert "Compare amounts and benefit types exactly" in service.ROLE_INSTRUCTIONS["reviewer"]
    assert "Only classify policy evidence as unavailable when it is absent" in service.ROLE_INSTRUCTIONS["reviewer"]


def test_reviewer_structured_claim_assessment_distinguishes_support_and_contradiction():
    evidence = _loyalty_evidence("Silver")
    base = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "unsupported",
            "rationale": "unsupported",
            "consistency": "consistent",
        },
        "findings": [{"severity": "high", "finding": "A benefit claim conflicts with the policy.",
                      "evidence_ref": "loyalty_policy", "classification": "unsupported_claim",
                      "claim_field": "recommendation"}],
        "missing_information": [],
        "recommendations": [],
    }
    result = _reviewer_output(base, evidence)
    assert result["claim_assessment"] == base["claim_assessment"]

    base["claim_assessment"]["consistency"] = "made_up"
    with pytest.raises(service.WorkflowError, match="claim_assessment"):
        _reviewer_output(base, evidence)

    base["claim_assessment"] = {
        "recommendation": "supported", "rationale": "supported", "consistency": "contradictory",
    }
    base["findings"][0]["classification"] = "contradiction"
    with pytest.raises(service.WorkflowError, match="identify both Worker claims"):
        _reviewer_output(base, evidence)


def _contradiction_case():
    worker = {
        "recommendation": "The request limit is 10 per day.",
        "rationale": "The request limit is 20 per day.",
    }
    evidence = [
        {"id": "source_a", "source": "policy-a", "status": "available", "content": worker["recommendation"]},
        {"id": "source_b", "source": "policy-b", "status": "available", "content": worker["rationale"]},
    ]
    output = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "contradictory",
        },
        "findings": [{
            "severity": "high", "classification": "contradiction", "claim_field": "multiple",
            "finding": "The sources give incompatible daily limits for the same request context.",
            "evidence_ref": "source_a", "conflicting_claims": dict(worker),
        }],
        "missing_information": [], "recommendations": ["Resolve the conflicting source limits."],
    }
    return output, evidence, worker


@pytest.mark.parametrize("attempt_index", [0, 1])
def test_actual_c67291b9_invalid_quotes_remain_rejected(attempt_index):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "reviewer_c67291b9.json").read_text())
    attempt = fixture["reviewer_attempts"][attempt_index]
    with pytest.raises(service.WorkflowError) as error:
        service._reviewer_output(attempt["output"], fixture["evidence"], fixture["worker_result"])
    assert str(error.value) == attempt["error"]


def _independent_checks(recommendation="supported", rationale="supported", consistency="consistent",
                        action="ready_for_human"):
    return {
        "support_checks": {
            "recommendation": {"assessment": recommendation, "explanation": "Recommendation check explanation.",
                               "evidence_refs": ["loyalty_policy"]},
            "rationale": {"assessment": rationale, "explanation": "Rationale check explanation.",
                          "evidence_refs": ["customer_facts", "loyalty_policy"]},
        },
        "consistency_check": {"assessment": consistency, "explanation": "Comparison explanation."},
        "action": action, "recommendations": [],
    }


def test_checks_preserve_model_judgments_and_label_application_added_quotes():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "reviewer_c67291b9.json").read_text())
    output = _independent_checks(recommendation="unsupported", action="not_supported")
    worker = dict(fixture["worker_result"], recommendation="Gold customers may receive a 99% discount.")
    result = service._reviewer_output(output, fixture["evidence"], worker)
    assert result["model_checks"] == output
    assert result["findings"][0]["finding"] == output["support_checks"]["recommendation"]["explanation"]
    assert result["findings"][0]["claim_quote"] == worker["recommendation"]
    assert result["application_added_provenance"] == [{
        "source": "application", "finding_index": 0, "worker_field": "recommendation",
        "claim_quote": worker["recommendation"],
    }]
    assert result["action"] == "not_supported"


def test_checks_keep_both_source_supported_claims_separate_from_contradiction():
    _legacy, evidence, worker = _contradiction_case()
    output = _independent_checks(consistency="contradictory", action="not_supported")
    output["support_checks"]["recommendation"]["evidence_refs"] = ["source_a"]
    output["support_checks"]["rationale"]["evidence_refs"] = ["source_b"]
    result = service._reviewer_output(output, evidence, worker)
    assert result["claim_assessment"] == {
        "recommendation": "supported", "rationale": "supported", "consistency": "contradictory",
    }
    assert result["findings"][0]["conflicting_claims"] == worker
    assert result["findings"][0]["finding"] == output["consistency_check"]["explanation"]
    assert result["application_added_provenance"][0]["source"] == "application"


@pytest.mark.parametrize("action", ["revise", "not_supported"])
def test_checks_do_not_rewrite_unjustified_negative_action_as_success(action):
    output = _independent_checks(action=action)
    with pytest.raises(service.WorkflowError, match="negative action without"):
        service._reviewer_output(output, _loyalty_evidence("Gold"), {"recommendation": "A", "rationale": "B"})


def test_checks_do_not_accept_unsupported_or_unavailable_claims_as_ready():
    evidence = _loyalty_evidence("Gold")
    worker = {"recommendation": "Unsupported benefit.", "rationale": "Policy is missing."}
    output = _independent_checks(recommendation="unsupported")
    with pytest.raises(service.WorkflowError, match="action conflicts"):
        service._reviewer_output(output, evidence, worker)
    output = _independent_checks(recommendation="evidence_unavailable", action="not_supported")
    evidence[-1]["status"] = "unavailable"
    result = service._reviewer_output(output, evidence, worker, {
        "worker_policy_evidence_ids": ["loyalty_policy"],
        "worker_required_evidence_ids": ["loyalty_policy"],
    })
    assert result["claim_assessment"]["recommendation"] == "evidence_unavailable"
    assert result["findings"][0]["classification"] == "missing_evidence"
    assert result["findings"][0]["finding"] == output["support_checks"]["recommendation"]["explanation"]
    assert result["application_added_findings"][0]["source"] == "application"


def test_truthful_abstention_support_does_not_override_missing_required_policy():
    evidence = _loyalty_evidence("Gold", policy_status="unavailable")
    worker = {"recommendation": "No approved benefits can be confirmed without policy evidence.",
              "rationale": "The supplied policy status is unavailable."}
    output = _independent_checks(action="not_supported")
    request_data = {"worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
                    "worker_policy_evidence_ids": ["loyalty_policy"]}
    result = service._reviewer_output(output, evidence, worker, request_data)
    assert result["claim_assessment"]["recommendation"] == "supported"
    assert result["model_checks"] == output
    assert result["application_added_findings"][0]["evidence_ref"] == "loyalty_policy"
    assert result["action"] == "not_supported"
    output["action"] = "ready_for_human"
    with pytest.raises(service.WorkflowError, match="policy evidence is unavailable"):
        service._reviewer_output(output, evidence, worker, request_data)


def test_real_reviewer_call_path_separates_source_context_from_field_comparison(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "reviewer_c67291b9.json").read_text())
    output = _independent_checks()
    calls = []

    def generate(role, prompt, timeout=None):
        assert 0 < timeout <= service.STAGE_TIMEOUT
        calls.append((role, prompt))
        service._call_diagnostics.last = {"eval_count": 1}
        if len(calls) == 1:
            return "deepseek-r1:8b", {"support_checks": output["support_checks"]}
        if len(calls) == 2:
            return "deepseek-r1:8b", {"consistency_check": output["consistency_check"]}
        return "deepseek-r1:8b", {key: output[key] for key in ("action", "recommendations")}

    monkeypatch.setattr(service, "_generate_model", generate)
    prompt = service._prompt("reviewer", {"goal": "Review.", "worker_policy_evidence_ids": ["loyalty_policy"]},
                             fixture["evidence"], worker=fixture["worker_result"])
    model, actual = service._call_model("reviewer", prompt)
    assert model == "deepseek-r1:8b"
    assert actual == output
    assert [role for role, _ in calls] == ["reviewer", "reviewer", "reviewer"]
    comparison = json.loads(calls[1][1].partition("CONSISTENCY REVIEW\n")[2])
    assert comparison["worker_fields"] == {key: fixture["worker_result"][key] for key in ("recommendation", "rationale")}
    assert set(comparison) == {"worker_fields"}
    decision = json.loads(calls[2][1].partition("REVIEW DECISION\n")[2])
    assert decision["required_source_status"] == {"loyalty_policy": "available"}
    assert decision["unresolved_findings"] == []
    assert decision["consistency"] == "consistent"
    assert "support_explanations" not in decision
    assert "Comparison explanation." not in calls[2][1]
    assert "EVIDENCE REGISTER" not in calls[1][1]
    assert "customer-loyalty-policy.md" not in calls[1][1]
    records = service._call_diagnostics.last["model_calls"]
    assert [record["phase"] for record in records] == ["source_support", "consistency", "decision"]
    assert records[0]["output"]["support_checks"] == output["support_checks"]
    assert records[1]["request"]["system"] == service.REVIEWER_CONSISTENCY_INSTRUCTIONS


def test_checks_cannot_cite_unseen_sources_but_reviewer_keeps_actual_worker_citations():
    evidence = _loyalty_evidence("Gold")
    request_data = {"worker_evidence_ids": ["customer_facts", "loyalty_policy"]}
    output = _independent_checks()
    output["support_checks"]["rationale"]["evidence_refs"] = ["mcp_profile"]
    worker = {"recommendation": "A", "rationale": "B", "evidence_refs": ["customer_facts", "loyalty_policy"]}
    with pytest.raises(service.WorkflowError, match="sources supplied to the Reviewer"):
        service._reviewer_output(output, evidence, worker, request_data)
    worker["evidence_refs"].append("mcp_profile")
    result = service._reviewer_output(output, evidence, worker, request_data)
    assert result["model_checks"]["support_checks"]["rationale"]["evidence_refs"] == ["mcp_profile"]


def test_new_model_checks_reach_human_review_with_exact_request_audit(client, monkeypatch):
    output = _independent_checks()
    for check in output["support_checks"].values():
        check["evidence_refs"] = ["facts", "policy"]
    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: (
        "configured-model", output if role == "reviewer" else _output_for(role),
    ))
    workflow_id = _start(client).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()
    assert workflow["status"] == "human_review"
    assert workflow["reviewer_result"]["model_checks"] == output
    assert workflow["reviewer_result"]["findings"] == []
    assert workflow["reviewer_result"]["application_added_provenance"] == []
    events = [json.loads(line) for line in service.AUDIT_PATH.read_text().splitlines()]
    saved_request = next(event["details"] for event in events if event["event"] == "reviewer_model_request")
    assert "WORKER RESULT" in saved_request["prompt"]
    assert "support_checks" in saved_request["format"]["properties"]
    assert saved_request["system"] == service.ROLE_INSTRUCTIONS["reviewer"]
    assert saved_request["model"] == service.ROLE_MODELS["reviewer"]
    accepted = client.post("/workflow/{}/review".format(workflow_id), json={"decision": "accept"})
    assert accepted.status_code == 200
    assert client.post("/workflow/{}/review".format(workflow_id), json={"decision": "reject"}).status_code == 409


@pytest.mark.parametrize("recommendation,rationale", [
    ("supported", "supported"), ("supported", "unsupported"),
    ("unsupported", "supported"), ("unsupported", "unsupported"),
])
def test_contradiction_is_independent_of_individual_source_support(recommendation, rationale):
    output, evidence, worker = _contradiction_case()
    output["claim_assessment"].update(recommendation=recommendation, rationale=rationale)
    result = service._reviewer_output(output, evidence, worker)
    assert result["claim_assessment"] == output["claim_assessment"]
    assert result["findings"] == output["findings"]
    assert result["action"] == "not_supported"


def test_contradiction_requires_matching_assessment_and_actual_worker_quotes():
    output, evidence, worker = _contradiction_case()
    output["claim_assessment"]["consistency"] = "consistent"
    with pytest.raises(service.WorkflowError, match="disagree about a contradiction"):
        service._reviewer_output(output, evidence, worker)

    output["claim_assessment"]["consistency"] = "contradictory"
    output["findings"][0]["conflicting_claims"]["rationale"] = "The request limit is unlimited."
    with pytest.raises(service.WorkflowError, match="quote the actual Worker rationale"):
        service._reviewer_output(output, evidence, worker)

    output["findings"] = []
    with pytest.raises(service.WorkflowError, match="requires a concrete contradiction finding"):
        service._reviewer_output(output, evidence, worker)


def test_contradiction_can_identify_the_primary_affected_field():
    output, evidence, worker = _contradiction_case()
    output["findings"][0]["claim_field"] = "recommendation"
    result = service._reviewer_output(output, evidence, worker)
    assert result["findings"] == output["findings"]


def test_repeated_worker_claim_cannot_be_used_as_opposing_quotes():
    output, evidence, worker = _contradiction_case()
    worker["rationale"] = worker["recommendation"]
    output["findings"][0]["conflicting_claims"] = dict(worker)
    with pytest.raises(service.WorkflowError, match="cannot use identical Worker claims"):
        service._reviewer_output(output, evidence, worker)


def test_legitimate_contradiction_cannot_be_marked_ready_for_human():
    output, evidence, worker = _contradiction_case()
    output["action"] = "ready_for_human"
    with pytest.raises(service.WorkflowError, match="action conflicts"):
        service._reviewer_output(output, evidence, worker)


def test_workflow_preserves_source_supported_contradiction_for_human_review(client, monkeypatch):
    review, evidence, worker = _contradiction_case()
    outputs = {
        "planner": {"tasks": [{"task": "Compare the source limits.", "evidence_refs": ["source_a", "source_b"]}]},
        "worker": dict(worker, policy_basis="source_a", evidence_refs=["source_a", "source_b"]),
        "reviewer": review,
    }
    monkeypatch.setattr(service, "_call_model", lambda role, _prompt: ("model", outputs[role]))
    response = client.post("/workflow", json={
        "subject_ref": "regression:conflicting-limits", "request": {"goal": "Review the daily limit."},
        "evidence": evidence, "max_revisions": 0,
    })
    assert response.status_code == 202
    workflow = client.get("/workflow/" + response.get_json()["workflow_id"]).get_json()
    assert workflow["status"] == "human_review"
    assert workflow["reviewer_result"]["action"] == "not_supported"
    assert workflow["reviewer_result"]["claim_assessment"] == review["claim_assessment"]
    assert workflow["reviewer_result"]["findings"] == review["findings"]
    assert workflow["human_decision"] is None


def test_reviewer_missing_required_claim_assessment_is_rejected():
    with pytest.raises(service.WorkflowError, match="claim_assessment must classify"):
        service._reviewer_output({
            "action": "ready_for_human", "findings": [], "missing_information": [],
            "recommendations": [],
        }, _loyalty_evidence("Silver"))


def test_reviewer_cannot_call_available_policy_unavailable():
    evidence = _loyalty_evidence("Silver")
    output = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "evidence_unavailable",
            "rationale": "supported",
            "consistency": "consistent",
        },
        "findings": [{"severity": "high", "finding": "A benefit claim lacks support.",
                      "evidence_ref": "loyalty_policy", "classification": "other",
                      "claim_field": "evidence"}],
        "missing_information": [], "recommendations": [],
    }
    with pytest.raises(service.WorkflowError, match="available policy evidence as unavailable"):
        _reviewer_output(output, evidence, request_data={
            "worker_policy_evidence_ids": ["loyalty_policy"],
        })


def test_reviewer_identifies_genuinely_unavailable_policy_separately():
    evidence = _loyalty_evidence("Silver")
    evidence[-1]["status"] = "unavailable"
    output = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "evidence_unavailable",
            "rationale": "supported",
            "consistency": "consistent",
        },
        "findings": [], "missing_information": ["Approved benefits cannot be checked."],
        "recommendations": [],
    }
    result = _reviewer_output(output, evidence, request_data={
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_policy_evidence_ids": ["loyalty_policy"],
    })
    assert result["claim_assessment"]["recommendation"] == "evidence_unavailable"
    assert result["findings"] == []
    assert result["application_added_findings"][0]["source"] == "application"
    assert "loyalty_policy is unavailable" in result["application_added_findings"][0]["finding"]


def test_optional_unavailable_mcp_does_not_force_policy_rejection():
    evidence = _loyalty_evidence("Silver")
    evidence[1]["status"] = "unavailable"
    output = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "supported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    result = _reviewer_output(output, evidence, request_data={
        "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
        "worker_policy_evidence_ids": ["loyalty_policy"],
    })

    assert result["action"] == "ready_for_human"
    assert result["application_added_findings"] == []


def test_reviewer_ready_action_conflicts_with_unsupported_assessment():
    evidence = _loyalty_evidence("Silver")
    output = {
        "action": "ready_for_human",
        "claim_assessment": {
            "recommendation": "unsupported", "rationale": "supported", "consistency": "consistent",
        },
        "findings": [], "missing_information": [], "recommendations": [],
    }
    with pytest.raises(service.WorkflowError, match="action conflicts"):
        _reviewer_output(output, evidence, request_data={
            "worker_policy_evidence_ids": ["loyalty_policy"],
        })


def test_jsonl_appends_are_valid_lines_under_concurrent_writes(client):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda number: service._append(service.AUDIT_PATH, {"n": number}), range(80)))
    records = [json.loads(line) for line in service.AUDIT_PATH.read_text().splitlines()]
    assert len(records) == 80
    assert {record["n"] for record in records} == set(range(80))



def test_ollama_http_failure_retains_actual_error_body(monkeypatch):
    monkeypatch.setattr(service, "_available_models", lambda **_kwargs: list(service.ROLE_MODELS.values()))
    response = service.requests.Response()
    response.status_code = 500
    response._content = b'{"error":"timed out waiting for model runner to start"}'
    monkeypatch.setattr(service.requests, "post", lambda *_args, **_kwargs: response)
    with pytest.raises(service.WorkflowError, match="timed out waiting for model runner"):
        service._generate_model("planner", "Request")
    assert service._call_diagnostics.raw_response == response.text
