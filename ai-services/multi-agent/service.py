"""Shared, native Planner/Worker/Reviewer orchestration service."""

import json
import copy
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("MULTI_AGENT_DATA_DIR", str(ROOT / "reports" / "multi-agent")))
HISTORY_PATH = DATA_DIR / "workflow_history.jsonl"
AUDIT_PATH = DATA_DIR / "coordination_audit.jsonl"
OLLAMA_URL = os.getenv("MULTI_AGENT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
ROLE_MODELS = {
    "planner": os.getenv("MULTI_AGENT_PLANNER_MODEL", "llama3.1:8b"),
    "worker": os.getenv("MULTI_AGENT_WORKER_MODEL", "qwen2.5:3b"),
    "reviewer": os.getenv("MULTI_AGENT_REVIEWER_MODEL", "deepseek-r1:8b"),
}
STAGE_TIMEOUT = int(os.getenv("MULTI_AGENT_STAGE_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
MAX_REVISIONS = max(0, min(2, int(os.getenv("MULTI_AGENT_MAX_REVISIONS", "1"))))
MAX_WORKERS = int(os.getenv("MULTI_AGENT_MAX_WORKERS", "4"))
CONTEXT_SIZE = max(4096, int(os.getenv("MULTI_AGENT_NUM_CTX", "8192")))
NUM_PREDICT = max(512, min(4096, int(os.getenv("MULTI_AGENT_NUM_PREDICT", "1024"))))

_write_lock = threading.RLock()
_call_diagnostics = threading.local()
_executor = None


class WorkflowError(RuntimeError):
    """A workflow cannot safely continue from its current stage."""


SUPPORT_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string", "enum": ["supported", "unsupported", "evidence_unavailable"]},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 300},
        "evidence_refs": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
    },
    "required": ["assessment", "explanation", "evidence_refs"],
    "additionalProperties": False,
}

CONSISTENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "consistency_check": {
            "type": "object",
            "properties": {
                "explanation": {"type": "string", "minLength": 1, "maxLength": 300},
                "assessment": {"type": "string", "enum": ["consistent", "contradictory"]},
            },
            "required": ["assessment", "explanation"], "additionalProperties": False,
        },
    },
    "required": ["consistency_check"], "additionalProperties": False,
}

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {"type": "array", "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
        "action": {"type": "string", "enum": ["ready_for_human", "revise", "not_supported"]},
    },
    "required": ["recommendations", "action"], "additionalProperties": False,
}


OUTPUT_SCHEMAS = {
    "planner": {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "maxLength": 240},
                    "evidence_refs": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
                },
                "required": ["task", "evidence_refs"],
                "additionalProperties": False,
            }},
        },
        "required": ["tasks"],
        "additionalProperties": False,
    },
    "worker": {
        "type": "object",
        "properties": {
            "recommendation": {"type": "string", "minLength": 1, "maxLength": 480},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 300},
            "policy_basis": {"type": "string", "minLength": 1},
            "evidence_refs": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
        },
        "required": ["recommendation", "rationale", "policy_basis", "evidence_refs"],
        "additionalProperties": False,
    },
    "reviewer": {
        "type": "object",
        "properties": {
            "support_checks": {
                "type": "object",
                "properties": {
                    "recommendation": SUPPORT_CHECK_SCHEMA,
                    "rationale": SUPPORT_CHECK_SCHEMA,
                },
                "required": ["recommendation", "rationale"],
                "additionalProperties": False,
            },
        },
        "required": ["support_checks"],
        "additionalProperties": False,
    },
}

ROLE_INSTRUCTIONS = {
    "planner": (
        "You are the Planner. Create a short ordered, model-generated plan of tasks using only the supplied request and evidence. "
        "Application-enforced acceptance criteria and constraints are supplied separately; do not repeat or rewrite them. "
        "Each task must cite exact evidence IDs from the supplied list. Do not invent verification requirements or facts. "
        "Keep every field concise and each array to the minimum entries needed. "
        "Return only the required output object; do not repeat the request or evidence."
    ),
    "worker": (
        "You are the Worker. Answer the request using the Planner's tasks and the supplied evidence. "
        "Write a concise informational recommendation, not instructions about what a worker should do. "
        "For a loyalty request, name the recorded tier in the recommendation, and take benefit wording only from the matching "
        "loyalty_policy section. Paraphrase faithfully while preserving every restriction and modal term, including "
        "may, either, only, and next. Do not add benefit options or imply that alternatives are cumulative. "
        "Keep the recommendation to at most two short sentences, rationale to one sentence, and policy_basis to the source ID/section. "
        "Do not discuss optional customer fields unrelated to the benefit or repeat the same evidence in multiple fields. "
        "The policy_basis field must contain one permitted evidence ID only, without quoted policy text. "
        "Never use MCP profile validation as benefit policy. Cite only permitted evidence IDs and include every "
        "ID listed in required_evidence_ids in evidence_refs. "
        "Do not invent facts, eligibility, or history; do not apply a benefit or change a customer record. "
        "A policy saying customers may receive benefits does not establish that this individual is eligible or entitled. "
        "When policy says customers may receive an option, preserve that qualification and describe it as an option; do not say this customer is eligible or will receive it. "
        "Do not repeat the plan, criteria, constraints, or request. Return only the required output object."
    ),
    "reviewer": (
        "Review the actual Worker fields against the supplied sources and request. "
        "For each support check, supported means supplied evidence establishes the material claim; unsupported means "
        "available evidence does not establish it; evidence_unavailable means needed policy evidence is absent or unavailable. "
        "Compare amounts and benefit types exactly, preserving alternatives, restrictions and whether a claim endorses or rejects a proposal. "
        "Policy options do not establish individual eligibility. Treat stronger entitlement or eligibility assertions as unsupported "
        "unless explicit facts establish them and application constraints permit that determination. "
        "The application contract describes workflow instructions; it is not policy evidence for customer eligibility or reward conditions. "
        "A correctly rejected unapproved proposal is not a benefit endorsed by the Worker. "
        "Use customer facts for stored fields and policy for approved benefits. MCP profile validation is not reward policy; "
        "missing optional phone/address does not establish reward ineligibility. "
        "The request lists the Worker's allowed sources and required citations. Do not demand that optional context or "
        "every Planner task be repeated in the rationale. Application requirements and model-generated tasks are labelled separately. "
        "Only classify policy evidence as unavailable when it is absent or its status is not available, never merely because a claim disagrees with it. "
        "Evaluate source support only. Conflicting sources can each support an individual Worker statement; consistency is reviewed separately. "
        "A truthful statement reporting a failed retrieval can be supported by the supplied source status, without establishing approved benefits. "
        "Give one short complete sentence for each explanation, preferably under 160 characters; do not repeat the Worker text. "
        "Cite the evidence IDs actually used. Never invent missing facts, eligibility rules or claims not present in the Worker text. "
        "Return only the required JSON object."
    ),
}

REVIEWER_CONSISTENCY_INSTRUCTIONS = (
    "Compare only the actual Worker recommendation and rationale with each other. "
    "Contradictory means they cannot both be true for the same subject, time and conditions. "
    "Restating the same options, paraphrasing and permitted alternatives are consistent. "
    "Endorsing something in one field while denying that same thing in the other is contradictory. "
    "Different asserted values for the same limit under the same conditions are contradictory even when separate sources support each statement. "
    "Source support is already reviewed and is independent of this comparison. Do not compare either Worker field with a policy instead of with the other field. "
    "Give one short complete sentence explaining the actual agreement or incompatibility. "
    "Return only the required JSON object; explain the relationship before selecting the assessment."
)

REVIEWER_DECISION_INSTRUCTIONS = (
    "Choose the final workflow action using only the supplied prior Reviewer judgments and application source statuses. "
    "Do not reassess source support or consistency, change previous judgments, or invent issues. "
    "Choose ready_for_human only when material claims are supported, the fields are consistent and required sources are available. "
    "Otherwise choose revise or not_supported for the specific unresolved problem. Do not invent eligibility rules. "
    "Recommendations address only unresolved findings; when none exist, return an empty list. Do not add profile checks or other requirements "
    "unless the request or supplied policy establishes that they are needed. Recommendations are corrections or next steps, never a restatement of the Worker answer. "
    "Use an empty list when none are needed. "
    "Ground every recommendation in the supplied evidence and application contract. A proposed business prerequisite must actually "
    "exist in the policy; never invent spending, purchase-history, status or eligibility conditions. A real supplied condition may be checked, "
    "but do not assert it is fulfilled without facts. Preserve policy qualifications and alternatives. "
    "Return only the required JSON object."
)

def _model_output_schema(role, prompt):
    """Constrain model evidence references to the IDs in the current request."""
    if role == "reviewer" and prompt.startswith("CONSISTENCY REVIEW\n"):
        return copy.deepcopy(CONSISTENCY_SCHEMA)
    if role == "reviewer" and prompt.startswith("REVIEW DECISION\n"):
        return copy.deepcopy(DECISION_SCHEMA)
    schema = copy.deepcopy(OUTPUT_SCHEMAS[role])
    marker = "PERMITTED EVIDENCE IDS (copy exactly; never invent an ID):\n"
    remainder = prompt.partition(marker)[2]
    evidence_ids = json.loads(remainder.split("\n\n", 1)[0]) if remainder else []

    if role == "planner":
        refs = schema["properties"]["tasks"]["items"]["properties"]["evidence_refs"]
        refs["items"]["enum"] = evidence_ids
        refs["maxItems"] = max(1, min(4, len(evidence_ids)))
    elif role == "worker":
        refs = schema["properties"]["evidence_refs"]
        refs["items"]["enum"] = evidence_ids
        refs["maxItems"] = max(1, min(4, len(evidence_ids)))
        contract = prompt.partition("EVIDENCE REGISTER")[0]
        contract_json = contract.partition("REQUEST CONTRACT (authoritative):\n")[2].strip()
        request_data = json.loads(contract_json) if contract_json else {}
        policy_ids = [item for item in request_data.get("policy_evidence_ids", []) if item in evidence_ids]
        schema["properties"]["policy_basis"]["enum"] = policy_ids or evidence_ids
    elif role == "reviewer":
        for check in schema["properties"]["support_checks"]["properties"].values():
            check["properties"]["evidence_refs"]["items"]["enum"] = evidence_ids
    return schema


def _now():
    return datetime.now(timezone.utc).isoformat()


def _append(path, record):
    """Append one complete JSONL record under a process-wide thread lock."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_redact(record), ensure_ascii=False, separators=(",", ":")) + "\n"
    with _write_lock, path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def _redact(value):
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if any(word in key.lower() for word in (
                "password", "secret", "token", "credential", "access_key", "private_key",
            )) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", value)
        return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    return value


def _history(workflow_id=None, subject_ref=None):
    if not HISTORY_PATH.exists():
        return []
    latest = {}
    with _write_lock, HISTORY_PATH.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if record.get("event") == "snapshot":
                latest[record["workflow"]["workflow_id"]] = record["workflow"]
    values = list(latest.values())
    if workflow_id:
        return [item for item in values if item["workflow_id"] == workflow_id]
    if subject_ref:
        values = [item for item in values if item.get("subject_ref") == subject_ref]
    return sorted(values, key=lambda item: item.get("created_at", ""), reverse=True)


def _save(workflow, event, details=None):
    now = _now()
    workflow["updated_at"] = now
    _append(HISTORY_PATH, {"event": "snapshot", "at": now, "workflow": workflow})
    _append(AUDIT_PATH, {
        "at": now,
        "workflow_id": workflow["workflow_id"],
        "subject_ref": workflow.get("subject_ref"),
        "event": event,
        "stage": workflow.get("stage"),
        "status": workflow.get("status"),
        "details": details or {},
    })


def _required_text(value, field, max_length=3000):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError("{} must be a non-empty string of at most {} characters".format(field, max_length))
    return value.strip()


def _string_list(value, field, maximum=12):
    if not isinstance(value, list) or len(value) > maximum:
        raise WorkflowError("{} must be a list with at most {} entries".format(field, maximum))
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 500:
            raise WorkflowError("{} entries must be non-empty strings up to 500 characters".format(field))
        result.append(item.strip())
    return result


def _available_models(timeout=4):
    response = requests.get(OLLAMA_URL + "/api/tags", timeout=timeout)
    response.raise_for_status()
    return [item.get("name", "") for item in response.json().get("models", [])]


def _model_request(role, prompt):
    instructions = ROLE_INSTRUCTIONS[role]
    if role == "reviewer" and prompt.startswith("CONSISTENCY REVIEW\n"):
        instructions = REVIEWER_CONSISTENCY_INSTRUCTIONS
    elif role == "reviewer" and prompt.startswith("REVIEW DECISION\n"):
        instructions = REVIEWER_DECISION_INSTRUCTIONS
    payload = {
        "model": ROLE_MODELS[role],
        "prompt": prompt,
        "system": instructions,
        "format": _model_output_schema(role, prompt),
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0.2, "num_predict": NUM_PREDICT, "num_ctx": CONTEXT_SIZE},
    }
    if role == "reviewer":
        # Keep Reviewer output within the configured JSON response budget.
        payload["think"] = False
    return payload


def _generate_model(role, prompt, timeout=None):
    started = time.monotonic()
    budget = STAGE_TIMEOUT if timeout is None else timeout
    _call_diagnostics.last = {}
    _call_diagnostics.raw_response = None
    model = ROLE_MODELS[role]
    available = _available_models(timeout=min(budget, 10))
    if model not in available:
        raise WorkflowError("configured {} model '{}' is unavailable; available models: {}".format(
            role, model, ", ".join(available) or "none"
        ))
    payload = _model_request(role, prompt)
    remaining = budget - (time.monotonic() - started)
    if remaining <= 0:
        raise requests.Timeout("Configured model-call time budget was exhausted before generation")
    response = requests.post(OLLAMA_URL + "/api/generate", json=payload, timeout=remaining)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        _call_diagnostics.raw_response = response.text[:1000]
        raise WorkflowError("{} model returned HTTP {}: {}".format(role, response.status_code, response.text[:1000])) from exc
    model_response = response.json()
    _call_diagnostics.last = {
        key: model_response[key]
        for key in (
            "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration",
            "eval_count", "eval_duration", "done_reason",
        )
        if key in model_response
    }
    raw = model_response.get("response", "")
    _call_diagnostics.raw_response = raw
    try:
        output = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise WorkflowError("{} returned malformed JSON (done_reason={}, eval_count={})".format(
            role, model_response.get("done_reason", "unknown"), model_response.get("eval_count", "unknown")
        )) from exc
    if not isinstance(output, dict):
        raise WorkflowError("{} output must be a JSON object".format(role))
    return model, output


def _call_model(role, prompt):
    if role != "reviewer":
        return _generate_model(role, prompt)
    calls = []
    deadline = time.monotonic() + STAGE_TIMEOUT

    def generate(check_prompt, phase):
        started = time.monotonic()
        record = {"phase": phase, "request": _model_request("reviewer", check_prompt)}
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout("Configured Reviewer stage time budget was exhausted")
            model, output = _generate_model("reviewer", check_prompt, timeout=remaining)
            record["output"] = output
            return model, output
        except (WorkflowError, requests.RequestException, ValueError) as exc:
            record.update(error=str(exc), response_text=getattr(_call_diagnostics, "raw_response", None))
            raise
        finally:
            record.update(elapsed_seconds=round(time.monotonic() - started, 3),
                          ollama=dict(getattr(_call_diagnostics, "last", {})))
            calls.append(record)

    try:
        feedback_marker = "\n\nAPPLICATION VALIDATION FEEDBACK (not evidence or a model finding):\n"
        support_prompt, _, feedback_text = prompt.partition(feedback_marker)
        if feedback_text:
            support_prompt += feedback_marker + feedback_text
        model, support = generate(support_prompt, "source_support")
        checks = support.get("support_checks")
        if not isinstance(checks, dict) or any(
            not isinstance(checks.get(field), dict)
            or checks[field].get("assessment") not in ("supported", "unsupported", "evidence_unavailable")
            for field in ("recommendation", "rationale")
        ):
            raise WorkflowError("Reviewer did not return valid source-support checks")
        worker = json.loads(prompt.partition("WORKER RESULT:\n")[2].split("\n\n", 1)[0])
        contract = json.loads(prompt.partition("REQUEST CONTRACT (authoritative):\n")[2].split("\n\n", 1)[0])
        sources = json.loads(prompt.partition("EVIDENCE REGISTER (full supplied content, source meaning and status):\n")[2].split("\n\n", 1)[0])
        comparison = {"worker_fields": {field: worker[field] for field in ("recommendation", "rationale")}}
        if feedback_text:
            comparison["application_validation_feedback"] = json.loads(feedback_text.split("\n", 1)[0])
        model, consistency = generate("CONSISTENCY REVIEW\n" + json.dumps(comparison, ensure_ascii=False), "consistency")
        decision_input = {
            "evidence": sources,
            "application_contract": contract,
            "source_support": {field: checks[field]["assessment"] for field in ("recommendation", "rationale")},
            "consistency": (consistency.get("consistency_check") or {}).get("assessment"),
            "required_source_status": contract.get("required_source_status", {}),
            "unresolved_findings": [
                {"worker_field": field, "assessment": check["assessment"], "explanation": check.get("explanation")}
                for field, check in checks.items() if check["assessment"] != "supported"
            ],
        }
        if decision_input["consistency"] == "contradictory":
            decision_input["unresolved_findings"].append({
                "worker_field": "multiple", "assessment": "contradictory",
                "explanation": consistency["consistency_check"].get("explanation"),
            })
        if feedback_text:
            decision_input["application_validation_feedback"] = json.loads(feedback_text.split("\n", 1)[0])
        model, decision = generate("REVIEW DECISION\n" + json.dumps(decision_input, ensure_ascii=False), "decision")
        return model, {"support_checks": checks, "consistency_check": consistency.get("consistency_check"),
                       "action": decision.get("action"), "recommendations": decision.get("recommendations")}
    finally:
        _call_diagnostics.last = {"model_calls": calls}


def _planner_output(output, evidence_ids, request_data=None):
    tasks = output.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 4:
        raise WorkflowError("Planner tasks must contain 1 to 4 ordered tasks")
    clean_tasks = []
    for task in tasks:
        if not isinstance(task, dict):
            raise WorkflowError("Planner task must be an object")
        refs = _string_list(task.get("evidence_refs", []), "task evidence_refs")
        if not refs or not set(refs).issubset(evidence_ids):
            raise WorkflowError("Planner referenced evidence that was not supplied")
        clean_tasks.append({
            "task": _required_text(task.get("task"), "task", 240),
            "evidence_refs": refs,
        })
    contract = (request_data or {}).get("plan_contract") or {}
    if not isinstance(contract, dict):
        raise WorkflowError("Planner plan_contract must be an object")
    return {
        "model_generated": {"tasks": clean_tasks},
        "application_enforced": {
            "acceptance_criteria": _string_list(contract.get("acceptance_criteria", []), "acceptance_criteria"),
            "constraints": _string_list(contract.get("constraints", []), "constraints"),
        },
    }


def _plan_is_complete(plan, evidence_ids, request_data):
    """Require a cited model plan and an unchanged application contract before review."""
    if not isinstance(plan, dict):
        return False
    generated = plan.get("model_generated")
    tasks = generated.get("tasks") if isinstance(generated, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        if not isinstance(task.get("task"), str) or not task["task"].strip():
            return False
        refs = task.get("evidence_refs")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in evidence_ids for ref in refs)):
            return False

    contract = (request_data or {}).get("plan_contract") or {}
    if not isinstance(contract, dict):
        return False
    enforced = plan.get("application_enforced")
    if not isinstance(enforced, dict):
        return False
    for field in ("acceptance_criteria", "constraints"):
        expected = contract.get(field, [])
        actual = enforced.get(field)
        if not isinstance(expected, list) or not isinstance(actual, list) or actual != expected:
            return False
        if any(not isinstance(item, str) or not item.strip() for item in actual):
            return False
    return True


def _worker_output(output, available_evidence_ids):
    refs = _string_list(output.get("evidence_refs"), "evidence_refs")
    if not refs or not set(refs).issubset(available_evidence_ids):
        raise WorkflowError("Worker must cite supplied evidence references")
    policy_basis = _required_text(output.get("policy_basis"), "policy_basis", 100)
    if policy_basis not in available_evidence_ids:
        raise WorkflowError("Worker policy_basis must be one supplied evidence ID")
    return {
        "recommendation": _required_text(output.get("recommendation"), "recommendation", 480),
        "rationale": _required_text(output.get("rationale"), "rationale", 300),
        "policy_basis": policy_basis,
        "evidence_refs": list(dict.fromkeys(refs)),
        "application_added_evidence_refs": [],
    }


def _validate_worker_contract(result, evidence, request_data):
    """Record application-added sources separately from citations made by the model."""
    available_ids = {item["id"] for item in evidence if item.get("status") == "available"}
    required = set(request_data.get("worker_required_evidence_ids", [])) & available_ids
    policy_ids = set(request_data.get("worker_policy_evidence_ids", [])) & available_ids
    if policy_ids and result.get("policy_basis") not in policy_ids:
        raise WorkflowError("Worker policy_basis must cite the supplied policy evidence")
    result["application_added_evidence_refs"] = sorted(required - set(result["evidence_refs"]))
    return result


def _review_evidence(evidence, request_data, worker=None):
    """Review the Worker's assigned sources, retaining every source it actually cites."""
    allowed = request_data.get("worker_evidence_ids")
    if allowed is None:
        return evidence
    ids = set(allowed) | set(request_data.get("worker_required_evidence_ids", []))
    ids.update(request_data.get("worker_policy_evidence_ids", []))
    ids.update((worker or {}).get("evidence_refs", []))
    ids.add((worker or {}).get("policy_basis"))
    return [item for item in evidence if item["id"] in ids]


def _required_source_status(evidence, request_data):
    required = set(request_data.get("worker_required_evidence_ids", []))
    required.update(request_data.get("worker_policy_evidence_ids", []))
    statuses = {item["id"]: item.get("status", "unavailable") for item in evidence}
    return {ref: statuses.get(ref, "absent") for ref in sorted(required)}


def _reviewer_checks_output(output, evidence, worker_result, request_data):
    """Adapt independent model judgments without generating or editing their explanations."""
    if not isinstance(worker_result, dict):
        raise WorkflowError("Reviewer checks require the actual Worker result")
    checks = output.get("support_checks")
    consistency = output.get("consistency_check")
    if not isinstance(checks, dict) or not isinstance(consistency, dict):
        raise WorkflowError("Reviewer must supply support checks and a consistency check")
    review_ids = {item["id"] for item in _review_evidence(evidence, request_data, worker_result)}
    assessments, findings, missing, provenance = {}, [], [], []
    for field in ("recommendation", "rationale"):
        check = checks.get(field)
        if not isinstance(check, dict) or check.get("assessment") not in (
            "supported", "unsupported", "evidence_unavailable",
        ):
            raise WorkflowError("Reviewer must assess the actual Worker {}".format(field))
        explanation = _required_text(check.get("explanation"), "Reviewer explanation", 300)
        refs = _string_list(check.get("evidence_refs"), "Reviewer evidence_refs", maximum=4)
        if not set(refs).issubset(review_ids):
            raise WorkflowError("Reviewer checks must cite sources supplied to the Reviewer")
        assessment = check["assessment"]
        assessments[field] = assessment
        if assessment != "evidence_unavailable" and not refs:
            raise WorkflowError("Reviewer source-support checks require an evidence reference")
        if assessment == "supported":
            continue
        policy_refs = set(request_data.get("worker_policy_evidence_ids", []))
        ref = next((item for item in refs if item in policy_refs), refs[0] if refs else None)
        finding = {
            "severity": "high", "finding": explanation, "evidence_ref": ref,
            "classification": "unsupported_claim" if assessment == "unsupported" else "missing_evidence",
            "claim_field": field, "conflicting_claims": None,
        }
        if assessment == "unsupported":
            finding["claim_quote"] = worker_result[field]
            provenance.append({"source": "application", "finding_index": len(findings),
                               "claim_quote": worker_result[field], "worker_field": field})
        else:
            missing.append(explanation)
        findings.append(finding)

    if consistency.get("assessment") not in ("consistent", "contradictory"):
        raise WorkflowError("Reviewer must compare the actual Worker fields for consistency")
    explanation = _required_text(consistency.get("explanation"), "Reviewer consistency explanation", 300)
    assessments["consistency"] = consistency["assessment"]
    if consistency["assessment"] == "contradictory":
        quotes = {field: worker_result[field] for field in ("recommendation", "rationale")}
        provenance.append({"source": "application", "finding_index": len(findings),
                           "conflicting_claims": quotes})
        findings.append({
            "severity": "high", "finding": explanation, "evidence_ref": None,
            "classification": "contradiction", "claim_field": "multiple", "conflicting_claims": quotes,
        })
    required_unavailable = any(status != "available" for status in _required_source_status(evidence, request_data).values())
    if output.get("action") in ("revise", "not_supported") and not findings and not required_unavailable:
        raise WorkflowError("Reviewer chose a negative action without an unsupported, unavailable or contradictory check")
    adapted = {
        "action": output.get("action"), "claim_assessment": assessments,
        "findings": findings, "missing_information": missing,
        "recommendations": output.get("recommendations"),
    }
    result = _reviewer_output(adapted, evidence, worker_result, request_data)
    result["model_checks"] = copy.deepcopy(output)
    result["application_added_provenance"] = provenance
    return result


def _reviewer_output(output, evidence, worker_result=None, request_data=None):
    """Validate reviewer structure while preserving its actual findings and action."""
    if "support_checks" in output or "consistency_check" in output:
        try:
            return _reviewer_checks_output(output, evidence, worker_result, request_data or {})
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
    evidence_ids = {item["id"] for item in evidence}
    action = output.get("action")
    if action not in ("ready_for_human", "revise", "not_supported"):
        raise WorkflowError("Reviewer action must be ready_for_human, revise, or not_supported")

    claim_assessment = output.get("claim_assessment")
    allowed = {
        "recommendation": {"supported", "unsupported", "evidence_unavailable", "not_applicable"},
        "rationale": {"supported", "unsupported", "evidence_unavailable", "not_applicable"},
        "consistency": {"consistent", "contradictory", "evidence_unavailable"},
    }
    if not isinstance(claim_assessment, dict) or any(
        claim_assessment.get(field) not in values for field, values in allowed.items()
    ):
        raise WorkflowError("Reviewer claim_assessment must classify recommendation, rationale, and consistency")
    requested_policy_ids = set((request_data or {}).get("worker_policy_evidence_ids", []))
    if requested_policy_ids:
        available_policy_ids = {
            item["id"] for item in evidence
            if item.get("id") in requested_policy_ids and item.get("status") == "available"
        }
        if available_policy_ids and claim_assessment["recommendation"] == "evidence_unavailable":
            raise WorkflowError("Reviewer classified available policy evidence as unavailable")
        if not available_policy_ids and action == "ready_for_human":
            raise WorkflowError("Reviewer cannot mark a policy-dependent recommendation ready when policy evidence is unavailable")

    findings = output.get("findings")
    if not isinstance(findings, list) or len(findings) > 5:
        raise WorkflowError("Reviewer findings must be a list of at most 5 objects")
    clean_findings = []
    for item in findings:
        if not isinstance(item, dict):
            raise WorkflowError("Reviewer finding must be an object")
        ref = item.get("evidence_ref")
        if ref is not None and ref not in evidence_ids:
            raise WorkflowError("Reviewer referenced evidence that was not supplied")
        clean_findings.append({
            "severity": item.get("severity") if item.get("severity") in ("low", "medium", "high") else "medium",
            "finding": _required_text(item.get("finding"), "finding", 300),
            "evidence_ref": ref,
            **({"claim_quote": item["claim_quote"]} if "claim_quote" in item else {}),
            **({
                "classification": item["classification"],
                "claim_field": item["claim_field"],
            } if item.get("classification") in ("unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other")
              and item.get("claim_field") in ("recommendation", "rationale", "multiple", "evidence") else {}),
        })
        if (
            item.get("classification") not in ("unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other")
            or item.get("claim_field") not in ("recommendation", "rationale", "multiple", "evidence")
        ):
            raise WorkflowError("Reviewer finding must classify its issue and Worker field")

    for finding, original in zip(clean_findings, findings):
        classification, field = finding.get("classification"), finding.get("claim_field")
        if classification != "unsupported_claim" and original.get("claim_quote") is not None:
            raise WorkflowError("Reviewer claim_quote is only valid for an unsupported_claim finding")
        if classification == "contradiction" and claim_assessment["consistency"] != "contradictory":
            raise WorkflowError("Reviewer finding and claim_assessment disagree about a contradiction")
        if classification == "contradiction":
            claims = original.get("conflicting_claims")
            if not isinstance(claims, dict):
                raise WorkflowError("Reviewer contradiction must identify both Worker claims")
            quoted = {}
            for name, limit in (("recommendation", 480), ("rationale", 300)):
                claim = claims.get(name)
                worker_text = (worker_result or {}).get(name)
                if (not isinstance(claim, str) or not claim.strip() or len(claim) > limit
                        or not isinstance(worker_text, str)
                        or " ".join(claim.split()).casefold() not in " ".join(worker_text.split()).casefold()):
                    raise WorkflowError("Reviewer contradiction must quote the actual Worker {}".format(name))
                quoted[name] = claim.strip()
            if " ".join(quoted["recommendation"].split()).casefold() == " ".join(quoted["rationale"].split()).casefold():
                raise WorkflowError("Reviewer contradiction cannot use identical Worker claims")
            finding["conflicting_claims"] = quoted
        elif original.get("conflicting_claims") is not None:
            raise WorkflowError("Reviewer conflicting_claims is only valid for a contradiction finding")
        if classification == "unsupported_claim":
            relevant = {
                "recommendation": ["recommendation"],
                "rationale": ["rationale"],
                "policy_basis": ["rationale"],
                "multiple": ["recommendation", "rationale"],
                "evidence": ["recommendation", "rationale"],
            }[field]
            if not any(claim_assessment[name] == "unsupported" for name in relevant):
                raise WorkflowError("Reviewer finding and claim_assessment disagree about unsupported claims")
            if worker_result is not None:
                claim = original.get("claim_quote")
                candidates = relevant if field in ("multiple", "evidence") else [field]
                normalized_claim = " ".join(claim.split()).casefold() if isinstance(claim, str) else ""
                if not normalized_claim or not any(
                    claim_field in candidates
                    and claim_assessment[claim_field] == "unsupported"
                    and normalized_claim in " ".join(str(worker_result.get(claim_field, "")).split()).casefold()
                    for claim_field in ("recommendation", "rationale")
                ):
                    raise WorkflowError("Reviewer unsupported-claim finding must quote the actual unsupported Worker field")

    if (claim_assessment["consistency"] == "contradictory"
            and not any(item["classification"] == "contradiction" for item in clean_findings)):
        raise WorkflowError("Reviewer contradictory assessment requires a concrete contradiction finding")

    unsupported_claim = any(
        claim_assessment[field] == "unsupported"
        for field in ("recommendation", "rationale")
    )
    if action == "ready_for_human" and (
        unsupported_claim or claim_assessment["consistency"] == "contradictory"
    ):
        raise WorkflowError(
            "Reviewer action conflicts with its unsupported or contradictory claim assessment"
        )
    if (action == "ready_for_human"
            and claim_assessment["recommendation"] == "evidence_unavailable"):
        raise WorkflowError("Reviewer cannot mark a policy-dependent recommendation ready when policy evidence is unavailable")

    missing_information = _string_list(output.get("missing_information", []), "missing_information")
    recommendations = _string_list(output.get("recommendations", []), "recommendations")
    required_status = _required_source_status(evidence, request_data or {})
    if action == "ready_for_human" and any(status != "available" for status in required_status.values()):
        raise WorkflowError("Reviewer cannot mark ready when required source evidence is unavailable")
    if (action == "not_supported" and not findings and not missing_information
            and not any(status != "available" for status in required_status.values())):
        raise WorkflowError("Reviewer returned not_supported without a concrete finding or missing-information item")
    if any(item in ("ready_for_human", "revise", "not_supported") for item in recommendations):
        raise WorkflowError("Reviewer put an action code in recommendations instead of the action field")
    application_added_findings = [
        {
            "source": "application",
            "severity": "high",
            "finding": "Required evidence {} is {} and was not available to support the recommendation.".format(
                ref, status
            ),
            "evidence_ref": ref,
            "classification": "missing_evidence",
            "claim_field": "evidence",
        }
        for ref, status in required_status.items()
        if status != "available"
    ]

    result = {
        "action": action,
        "findings": clean_findings,
        "missing_information": missing_information,
        "recommendations": recommendations,
        "application_added_findings": application_added_findings,
    }
    if claim_assessment is not None:
        result["claim_assessment"] = {field: claim_assessment[field] for field in allowed}
    return result


def _prompt(role, request_data, evidence, plan=None, worker=None, findings=None, revision=0,
            validation_feedback=None):
    if role == "planner":
        # Keep application-owned criteria out of the model-generated plan.
        role_request = {"goal": request_data.get("goal")}
        allowed = request_data.get("worker_evidence_ids")
        role_evidence = [item for item in evidence if allowed is None or item["id"] in allowed]
    elif role == "worker":
        allowed = request_data.get("worker_evidence_ids")
        role_request = {"goal": request_data.get("goal")}
        if request_data.get("worker_required_evidence_ids"):
            role_request["required_evidence_ids"] = request_data["worker_required_evidence_ids"]
        if request_data.get("worker_policy_evidence_ids"):
            role_request["policy_evidence_ids"] = request_data["worker_policy_evidence_ids"]
        role_evidence = [item for item in evidence if allowed is None or item["id"] in allowed]
    else:
        role_request = {"goal": request_data.get("goal")}
        for source, target in (("worker_evidence_ids", "worker_evidence_ids"),
                               ("worker_required_evidence_ids", "required_evidence_ids"),
                               ("worker_policy_evidence_ids", "policy_evidence_ids")):
            if source in request_data:
                role_request[target] = request_data[source]
        role_request["required_source_status"] = _required_source_status(evidence, request_data)
        role_evidence = _review_evidence(evidence, request_data, worker)

    if role != "planner":
        role_request["plan_contract"] = request_data.get("plan_contract", {})

    prompt_evidence = []
    for item in role_evidence:
        prompt_item = dict(item)
        try:
            prompt_item["content"] = json.loads(item["content"])
        except (ValueError, TypeError):
            pass
        prompt_evidence.append(prompt_item)

    sections = ["REQUEST CONTRACT (authoritative):\n" + json.dumps(role_request, ensure_ascii=False)]
    sections.append("EVIDENCE REGISTER (full supplied content, source meaning and status):\n" +
                    json.dumps(prompt_evidence, ensure_ascii=False))
    evidence_ids = [item["id"] for item in role_evidence]
    if role == "worker":
        evidence_ids = [item["id"] for item in role_evidence if item["status"] == "available"]
    sections.append("PERMITTED EVIDENCE IDS (copy exactly; never invent an ID):\n" +
                    json.dumps(evidence_ids, ensure_ascii=False))
    if plan is not None:
        sections.append("PLANNER OUTPUT:\n" + json.dumps(plan, ensure_ascii=False))
    if worker is not None:
        # Citation IDs are checked by the application; present only actual claims for model review.
        role_worker = {field: worker[field] for field in ("recommendation", "rationale")} if role == "reviewer" else worker
        sections.append("WORKER RESULT:\n" + json.dumps(role_worker, ensure_ascii=False))
    if findings is not None:
        sections.append("REVIEW FINDINGS TO ADDRESS:\n" + json.dumps(findings, ensure_ascii=False))
    if validation_feedback:
        sections.append(
            "APPLICATION VALIDATION FEEDBACK (not evidence or a model finding):\n"
            + json.dumps(validation_feedback, ensure_ascii=False)
            + "\nReassess the original claims against the evidence independently. Correct the invalid structure or internal contradiction; do not treat this application feedback as policy evidence."
        )
    if role == "worker":
        sections.append("REVISION NUMBER: {}".format(revision))
    return "\n\n".join(sections)


def _run_workflow(workflow_id):
    workflow = _history(workflow_id=workflow_id)[0]
    evidence_ids = {item["id"] for item in workflow["evidence"]}
    available_evidence_ids = {item["id"] for item in workflow["evidence"] if item["status"] == "available"}
    allowed_worker_ids = workflow["request"].get("worker_evidence_ids")
    planner_evidence_ids = evidence_ids
    if allowed_worker_ids is not None:
        available_evidence_ids &= set(allowed_worker_ids)
        planner_evidence_ids = evidence_ids & set(allowed_worker_ids)
    try:
        workflow["status"], workflow["stage"] = "planning", "planner"
        _save(workflow, "stage_started", {"role": "planner", "model": ROLE_MODELS["planner"]})
        model, raw = _call_model("planner", _prompt("planner", workflow["request"], workflow["evidence"]))
        plan = _planner_output(raw, planner_evidence_ids, workflow["request"])
        workflow["roles"].append({"role": "planner", "model": model, "completed_at": _now()})
        workflow["plan"] = plan
        if not _plan_is_complete(workflow["plan"], evidence_ids, workflow["request"]):
            raise WorkflowError("Planner did not produce a complete required plan")
        _save(workflow, "stage_completed", {"role": "planner", "model": model, "plan": workflow["plan"]})

        for revision in range(workflow["max_revisions"] + 1):
            workflow["status"], workflow["stage"] = ("revising" if revision else "working"), "worker"
            _save(workflow, "stage_started", {"role": "worker", "revision": revision, "model": ROLE_MODELS["worker"]})
            worker_plan = workflow["plan"]
            model, raw = _call_model("worker", _prompt(
                "worker", workflow["request"], workflow["evidence"], worker_plan,
                workflow.get("worker_result"),
                (workflow.get("reviewer_result") or {}).get("findings"), revision,
            ))
            result = _validate_worker_contract(
                _worker_output(raw, available_evidence_ids), workflow["evidence"], workflow["request"]
            )
            workflow["roles"].append({"role": "worker", "model": model, "revision": revision, "completed_at": _now()})
            workflow["worker_result"] = result
            _save(workflow, "stage_completed", {"role": "worker", "revision": revision, "result": workflow["worker_result"]})

            workflow["status"], workflow["stage"] = "reviewing", "reviewer"
            workflow["reviewer_result"] = None
            validation_feedback = None
            while True:
                _save(workflow, "stage_started", {
                    "role": "reviewer", "model": ROLE_MODELS["reviewer"],
                    "validation_retry": workflow["reviewer_validation_retries"],
                })
                reviewer_prompt = _prompt(
                    "reviewer", workflow["request"], workflow["evidence"], workflow["plan"],
                    workflow["worker_result"], revision=revision,
                    validation_feedback=validation_feedback,
                )
                reviewer_started = time.monotonic()
                _call_diagnostics.last = {}
                _call_diagnostics.raw_response = None
                _save(workflow, "reviewer_model_request", _model_request("reviewer", reviewer_prompt))
                try:
                    model, raw = _call_model("reviewer", reviewer_prompt)
                except (requests.RequestException, WorkflowError, ValueError) as exc:
                    elapsed = round(time.monotonic() - reviewer_started, 3)
                    attempt = {
                        "attempt": workflow["reviewer_validation_retries"] + 1,
                        "model": ROLE_MODELS["reviewer"],
                        "elapsed_seconds": elapsed,
                        "prompt_characters": len(reviewer_prompt),
                        "error": str(exc)[:500],
                        "output": None,
                        "response_text": getattr(_call_diagnostics, "raw_response", None),
                        "ollama": dict(getattr(_call_diagnostics, "last", {})),
                        "at": _now(),
                    }
                    workflow["reviewer_validation_log"].append(attempt)
                    workflow["roles"].append({
                        "role": "reviewer", "model": ROLE_MODELS["reviewer"],
                        "elapsed_seconds": elapsed, "validation_status": "call_failed",
                        "validation_error": str(exc)[:500],
                    })
                    _save(workflow, "reviewer_call_failed", attempt)
                    raise
                reviewer_elapsed = round(time.monotonic() - reviewer_started, 3)
                reviewer_metrics = dict(getattr(_call_diagnostics, "last", {}))
                try:
                    reviewed = _reviewer_output(
                        raw, workflow["evidence"], workflow["worker_result"], workflow["request"]
                    )
                except (WorkflowError, ValueError) as exc:
                    workflow["roles"].append({
                        "role": "reviewer", "model": model, "completed_at": _now(),
                        "elapsed_seconds": reviewer_elapsed,
                        "ollama": reviewer_metrics,
                        "validation_status": "failed", "validation_error": str(exc)[:500],
                    })
                    attempt = {
                        "attempt": workflow["reviewer_validation_retries"] + 1,
                        "error": str(exc)[:500], "model": model, "at": _now(),
                        "elapsed_seconds": reviewer_elapsed,
                        "prompt_characters": len(reviewer_prompt), "ollama": reviewer_metrics,
                        "output": raw,
                    }
                    workflow["reviewer_validation_log"].append(attempt)
                    _save(workflow, "reviewer_validation_failed", attempt)
                    if workflow["reviewer_validation_retries"] >= workflow["max_revisions"]:
                        raise WorkflowError(
                            "Reviewer response remained invalid after the configured retry: {}".format(exc)
                        ) from exc
                    workflow["reviewer_validation_retries"] += 1
                    validation_feedback = {"error": str(exc)[:500]}
                    continue
                workflow["roles"].append({
                    "role": "reviewer", "model": model, "completed_at": _now(),
                    "elapsed_seconds": reviewer_elapsed,
                    "ollama": reviewer_metrics,
                    "validation_status": "passed",
                })
                workflow["reviewer_result"] = reviewed
                break
            workflow["revision_count"] = revision
            _save(workflow, "stage_completed", {"role": "reviewer", "result": workflow["reviewer_result"]})
            if workflow["reviewer_result"]["action"] != "revise" or revision >= workflow["max_revisions"]:
                break

        if not _plan_is_complete(workflow.get("plan"), evidence_ids, workflow["request"]):
            raise WorkflowError("Workflow cannot reach human review without a complete Planner plan")
        workflow["status"], workflow["stage"] = "human_review", "human_review"
        workflow["completion_gate"] = {
            "planner_completed": _plan_is_complete(workflow.get("plan"), evidence_ids, workflow["request"]),
            "worker_completed": True,
            "reviewer_completed": True,
            "human_decision_recorded": False,
        }
        _save(workflow, "human_review_required", {"action": workflow["reviewer_result"]["action"]})
    except (WorkflowError, requests.RequestException, ValueError, KeyError) as exc:
        workflow["status"], workflow["stage"] = "failed", workflow.get("stage", "planning")
        workflow["failure"] = str(exc)[:1000]
        workflow["completion_gate"] = {
            "planner_completed": _plan_is_complete(
                workflow.get("plan"), evidence_ids, workflow["request"]
            ),
            "worker_completed": workflow.get("worker_result") is not None,
            "reviewer_completed": workflow.get("reviewer_result") is not None,
            "human_decision_recorded": False,
        }
        _save(workflow, "stage_failed", {"error": workflow["failure"]})


def _review_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    decision = payload.get("decision")
    if decision not in ("accept", "partial_accept", "reject"):
        raise ValueError("decision must be accept, partial_accept, or reject")
    feedback = payload.get("feedback", "")
    if not isinstance(feedback, str) or len(feedback) > 2000:
        raise ValueError("feedback must be a string up to 2000 characters")
    result = {"decision": decision, "feedback": feedback.strip(), "reviewed_at": _now()}
    if decision == "partial_accept":
        if not result["feedback"]:
            raise ValueError("Feedback is required for partial acceptance.")
        corrected = payload.get("corrected_output")
        if not isinstance(corrected, dict):
            raise ValueError("partial acceptance requires corrected_output")
        result["corrected_output"] = {
            "recommendation": _required_text(corrected.get("recommendation"), "corrected recommendation", 1200),
            "rationale": _required_text(corrected.get("rationale"), "corrected rationale", 1600),
        }
        result["accepted_fields"] = _string_list(payload.get("accepted_fields"), "accepted_fields", 4)
        result["unresolved_issues"] = _string_list(payload.get("unresolved_issues"), "unresolved_issues", 12)
        if not result["accepted_fields"] or not result["unresolved_issues"]:
            raise ValueError("partial acceptance requires accepted_fields and unresolved_issues")
    elif decision == "reject":
        if not result["feedback"]:
            raise ValueError("rejection requires feedback")
        result["unresolved_issues"] = _string_list(payload.get("unresolved_issues", []), "unresolved_issues", 12)
    return result


def create_app():
    global _executor
    app = Flask(__name__)
    if _executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="multi-agent")

    @app.get("/health")
    def health():
        try:
            available = _available_models(timeout=3)
            missing = {role: model for role, model in ROLE_MODELS.items() if model not in available}
            status = "ok" if not missing else "degraded"
            return jsonify({
                "service": "multi-agent",
                "status": status,
                "roles": ROLE_MODELS,
                "available_models": available,
                "missing_role_models": missing,
            }), (200 if not missing else 503)
        except requests.RequestException as exc:
            return jsonify({"service": "multi-agent", "status": "degraded", "error": str(exc)}), 503

    @app.post("/workflow")
    def start_workflow():
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            subject_ref = _required_text(payload.get("subject_ref"), "subject_ref", 120)
            request_data = payload.get("request")
            if not isinstance(request_data, dict) or not request_data:
                raise ValueError("request must be a non-empty JSON object")
            evidence = payload.get("evidence")
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
                raise ValueError("evidence must contain 1 to 20 references")
            clean_evidence, seen = [], set()
            for item in evidence:
                if not isinstance(item, dict):
                    raise ValueError("each evidence item must be an object")
                evidence_id = _required_text(item.get("id"), "evidence id", 100)
                if evidence_id in seen:
                    raise ValueError("evidence ids must be unique")
                if item.get("status", "available") not in ("available", "insufficient", "unavailable"):
                    raise ValueError("evidence status must be available, insufficient, or unavailable")
                seen.add(evidence_id)
                clean_evidence.append({
                    "id": evidence_id,
                    "source": _required_text(item.get("source"), "evidence source", 120),
                    "status": item.get("status", "available"),
                    "content": _required_text(item.get("content"), "evidence content", 8000),
                    "meaning": _required_text(item.get("meaning"), "evidence meaning", 300)
                    if item.get("meaning") else "",
                })
            revision_limit = payload.get("max_revisions", MAX_REVISIONS)
            if type(revision_limit) is not int or not 0 <= revision_limit <= 2:
                raise ValueError("max_revisions must be an integer from 0 to 2")
            workflow = {
                "workflow_id": str(uuid.uuid4()),
                "subject_ref": subject_ref,
                "request": request_data,
                "evidence": clean_evidence,
                "created_at": _now(),
                "updated_at": _now(),
                "status": "queued",
                "stage": "queued",
                "plan": None,
                "worker_result": None,
                "reviewer_result": None,
                "human_decision": None,
                "roles": [],
                "revision_count": 0,
                "reviewer_validation_retries": 0,
                "reviewer_validation_log": [],
                "max_revisions": revision_limit,
                "completion_gate": {"planner_completed": False, "worker_completed": False,
                                    "reviewer_completed": False, "human_decision_recorded": False},
            }
            _save(workflow, "workflow_created", {"subject_ref": subject_ref})
            _executor.submit(_run_workflow, workflow["workflow_id"])
            return jsonify({"workflow_id": workflow["workflow_id"], "status": "queued"}), 202
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/workflow/status/<workflow_id>")
    @app.get("/workflow/<workflow_id>")
    def workflow_status(workflow_id):
        matches = _history(workflow_id=workflow_id)
        if not matches:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify(matches[0])

    @app.get("/workflow/history")
    def workflow_history():
        subject_ref = request.args.get("subject_ref")
        items = _history(subject_ref=subject_ref)
        return jsonify({"count": len(items), "workflows": items[:100]})

    @app.post("/workflow/<workflow_id>/review")
    def human_review(workflow_id):
        with _write_lock:
            matches = _history(workflow_id=workflow_id)
            if not matches:
                return jsonify({"error": "workflow not found"}), 404
            workflow = matches[0]
            if workflow["status"] != "human_review":
                return jsonify({"error": "workflow is not awaiting human review", "status": workflow["status"]}), 409
            try:
                decision = _review_payload(request.get_json(silent=True))
            except (ValueError, WorkflowError) as exc:
                return jsonify({"error": str(exc)}), 400
            workflow["human_decision"] = decision
            workflow["status"] = {
                "accept": "accepted", "partial_accept": "partially_accepted", "reject": "rejected",
            }[decision["decision"]]
            workflow["stage"] = "completed"
            workflow["completion_gate"]["human_decision_recorded"] = True
            _save(workflow, "human_decision_recorded", decision)
            return jsonify(workflow)

    return app


app = create_app()
