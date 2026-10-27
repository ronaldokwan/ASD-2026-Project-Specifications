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
        "findings": [{"severity": "low", "finding": "The result cites the supplied policy.", "evidence_ref": "policy"}],
        "missing_information": [],
        "recommendations": ["Administrator should review before use."],
    }


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

    assert calls == ["planner"] * service.STAGE_ATTEMPTS
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
    role_models = {"planner": "planner-local", "worker": "worker-local", "reviewer": "deepseek-r1:8b"}
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
        _model, output = service._call_model(role, prompt)
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
        return schema["properties"]["findings"]["items"]["properties"]["evidence_ref"]["enum"]

    assert all("synthetic_id" in constrained_ids(role, call["payload"]["format"])
               for call, role in zip(calls, role_models))
    assert calls[1]["payload"]["format"]["properties"]["policy_basis"]["enum"] == ["synthetic_id"]
    assert calls[0]["payload"]["format"]["properties"]["tasks"]["items"]["properties"]["evidence_refs"]["maxItems"] == 1
    assert calls[1]["payload"]["format"]["properties"]["evidence_refs"]["maxItems"] == 1
    assert all(call["payload"]["options"]["num_predict"] == service.NUM_PREDICT for call in calls)
    assert all(call["payload"]["options"]["num_ctx"] >= 4096 for call in calls)
    assert "think" not in calls[0]["payload"]
    assert "think" not in calls[1]["payload"]
    assert calls[2]["payload"]["think"] is False  # only DeepSeek R1 models get think=False
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
                                      plan={"tasks": []}, worker={"recommendation": "Example"})
    assert '"mcp_profile"' not in worker_prompt
    permitted = worker_prompt.split("PERMITTED EVIDENCE IDS (copy exactly; never invent an ID):\n", 1)[1].split("\n\n", 1)[0]
    assert json.loads(permitted) == ["customer_facts", "loyalty_policy"]
    assert '"mcp_profile"' in reviewer_prompt
    assert "not reward policy" in reviewer_prompt
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
    assert worker_schema["properties"]["rationale"]["maxLength"] == 600
    assert reviewer_schema["properties"]["findings"]["items"]["properties"]["finding"]["maxLength"] >= 300


def test_reviewer_output_is_preserved_for_human_review_without_application_rewriting():
    evidence = _loyalty_evidence("Gold")
    recommendation = "Gold customers may receive fifteen percent off the next purchase or early access to the next seasonal sale."
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
        "action": "ready_for_human", "findings": [], "missing_information": [], "recommendations": [],
    }, evidence, {"recommendation": "Consider a benefit.", "rationale": "Policy unavailable.", "policy_basis": "None"})
    assert result["action"] == "not_supported"
    assert any("loyalty_policy evidence is insufficient" in item for item in result["missing_information"])
    assert any(item["evidence_ref"] == "loyalty_policy" for item in result["findings"])


def test_reviewer_negative_result_is_not_relabelled_as_approval():
    evidence = _loyalty_evidence("Silver")
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
    result = service._reviewer_output({
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
        service._reviewer_output(output, evidence, {"recommendation": "Supported by evidence."})
    output["findings"] = [{"severity": "low", "finding": "A problem was found.", "evidence_ref": "loyalty_policy"}]
    with pytest.raises(service.WorkflowError, match="action code in recommendations"):
        service._reviewer_output(output, evidence, {"recommendation": "Supported by evidence."})


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
    assert "compare them with each other" in service.ROLE_INSTRUCTIONS["reviewer"]
    assert "Compare amounts and benefit types exactly" in service.ROLE_INSTRUCTIONS["reviewer"]
    assert "Only classify policy evidence as unavailable when it is absent" in service.ROLE_INSTRUCTIONS["reviewer"]


def test_reviewer_structured_claim_assessment_distinguishes_support_and_contradiction():
    evidence = _loyalty_evidence("Silver")
    base = {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "unsupported",
            "rationale": "unsupported",
            "consistency": "contradictory",
        },
        "findings": [{"severity": "high", "finding": "A benefit claim conflicts with the policy.",
                      "evidence_ref": "loyalty_policy", "classification": "unsupported_claim",
                      "claim_field": "recommendation"}],
        "missing_information": [],
        "recommendations": [],
    }
    result = service._reviewer_output(base, evidence)
    assert result["claim_assessment"] == base["claim_assessment"]

    base["claim_assessment"]["consistency"] = "made_up"
    with pytest.raises(service.WorkflowError, match="claim_assessment"):
        service._reviewer_output(base, evidence)

    base["claim_assessment"] = {
        "recommendation": "supported", "rationale": "supported", "consistency": "contradictory",
    }
    base["findings"][0]["classification"] = "contradiction"
    with pytest.raises(service.WorkflowError, match="no unsupported Worker claim"):
        service._reviewer_output(base, evidence)


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
        service._reviewer_output(output, evidence, request_data={
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
    result = service._reviewer_output(output, evidence, request_data={
        "worker_policy_evidence_ids": ["loyalty_policy"],
    })
    assert result["claim_assessment"]["recommendation"] == "evidence_unavailable"
    assert any("loyalty_policy evidence was unavailable" in item["finding"] for item in result["findings"])


def test_jsonl_appends_are_valid_lines_under_concurrent_writes(client):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda number: service._append(service.AUDIT_PATH, {"n": number}), range(80)))
    records = [json.loads(line) for line in service.AUDIT_PATH.read_text().splitlines()]
    assert len(records) == 80
    assert {record["n"] for record in records} == set(range(80))


INCONSISTENT_REVIEW = {
    "action": "not_supported",
    "claim_assessment": {"recommendation": "supported", "rationale": "supported",
                         "consistency": "contradictory"},
    "findings": [{"severity": "high", "finding": "The rationale contradicts the policy.",
                  "evidence_ref": "policy", "classification": "contradiction",
                  "claim_field": "rationale"}],
    "missing_information": [],
    "recommendations": ["Correct the rationale."],
}


def test_rejected_output_is_retried_with_the_reason_fed_back(client, monkeypatch):
    prompts = []

    def fake_call(role, prompt):
        prompts.append((role, prompt))
        if role == "reviewer" and len([p for p in prompts if p[0] == "reviewer"]) == 1:
            return "test-model", INCONSISTENT_REVIEW
        return "test-model", _output_for(role)

    monkeypatch.setattr(service, "_call_model", fake_call)
    workflow_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    reviewer_prompts = [prompt for role, prompt in prompts if role == "reviewer"]
    assert len(reviewer_prompts) == 2
    assert "YOUR PREVIOUS OUTPUT WAS REJECTED" in reviewer_prompts[1]
    assert "no unsupported Worker claim" in reviewer_prompts[1]
    assert workflow["status"] == "human_review"
    assert "reconciled" not in workflow["reviewer_result"]
    events = [json.loads(line)["event"] for line in service.AUDIT_PATH.read_text().splitlines()]
    assert "stage_output_rejected" in events


def test_persistently_inconsistent_reviewer_reaches_human_review_flagged(client, monkeypatch):
    calls = []

    def fake_call(role, _prompt):
        calls.append(role)
        return "test-model", INCONSISTENT_REVIEW if role == "reviewer" else _output_for(role)

    monkeypatch.setattr(service, "_call_model", fake_call)
    workflow_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    assert calls.count("reviewer") == service.STAGE_ATTEMPTS
    assert workflow["status"] == "human_review"
    review = workflow["reviewer_result"]
    assert review["reconciled"] is True
    assert review["action"] == "not_supported"
    assert review["claim_assessment"]["recommendation"] == "unsupported"
    assert review["claim_assessment"]["rationale"] == "unsupported"
    assert review["findings"][0]["finding"] == "The rationale contradicts the policy."
    assert "internally inconsistent" in review["findings"][-1]["finding"]
    assert workflow["completion_gate"]["reviewer_completed"] is True
    events = [json.loads(line)["event"] for line in service.AUDIT_PATH.read_text().splitlines()]
    assert "reviewer_output_reconciled" in events
    accepted = client.post("/workflow/{}/review".format(workflow_id),
                           json={"decision": "reject", "feedback": "Reviewer was unreliable."})
    assert accepted.get_json()["status"] == "rejected"


def test_reviewer_without_any_parsable_output_still_fails(client, monkeypatch):
    def fake_call(role, _prompt):
        if role == "reviewer":
            raise service.WorkflowError("reviewer returned malformed JSON")
        return "test-model", _output_for(role)

    monkeypatch.setattr(service, "_call_model", fake_call)
    workflow_id = _start(client, max_revisions=0).get_json()["workflow_id"]
    workflow = client.get("/workflow/" + workflow_id).get_json()

    assert workflow["status"] == "failed"
    assert "malformed JSON" in workflow["failure"]
