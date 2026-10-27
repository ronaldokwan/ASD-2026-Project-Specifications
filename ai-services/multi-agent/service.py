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
    "reviewer": os.getenv("MULTI_AGENT_REVIEWER_MODEL", "llama3.1:8b"),
}
STAGE_TIMEOUT = int(os.getenv("MULTI_AGENT_STAGE_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
MAX_REVISIONS = max(0, min(2, int(os.getenv("MULTI_AGENT_MAX_REVISIONS", "1"))))
MAX_WORKERS = int(os.getenv("MULTI_AGENT_MAX_WORKERS", "4"))
# Each role gets this many calls when its output fails validation; the rejection
# reason is fed back so the model can correct itself.
STAGE_ATTEMPTS = max(1, min(4, int(os.getenv("MULTI_AGENT_STAGE_ATTEMPTS", "3"))))
CONTEXT_SIZE = max(4096, int(os.getenv("MULTI_AGENT_NUM_CTX", "8192")))
NUM_PREDICT = max(512, min(4096, int(os.getenv("MULTI_AGENT_NUM_PREDICT", "1024"))))

_write_lock = threading.RLock()
_executor = None


class WorkflowError(RuntimeError):
    """A workflow cannot safely continue from its current stage."""


class StageOutputRejected(WorkflowError):
    """Every attempt of one role produced output that failed validation."""

    def __init__(self, role, error, raw):
        super().__init__("{} output rejected after {} attempt(s): {}".format(role, STAGE_ATTEMPTS, error))
        self.role = role
        self.error = error
        self.raw = raw


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
            "rationale": {"type": "string", "minLength": 1, "maxLength": 600},
            "policy_basis": {"type": "string", "minLength": 1},
            "evidence_refs": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
        },
        "required": ["recommendation", "rationale", "policy_basis", "evidence_refs"],
        "additionalProperties": False,
    },
    "reviewer": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ready_for_human", "revise", "not_supported"]},
            "claim_assessment": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string", "enum": ["supported", "unsupported", "evidence_unavailable", "not_applicable"], "description": "Use evidence_unavailable only when the relevant policy source is absent or unavailable."},
                    "rationale": {"type": "string", "enum": ["supported", "unsupported", "evidence_unavailable", "not_applicable"], "description": "Use evidence_unavailable only when the relevant policy source is absent or unavailable."},
                    "consistency": {"type": "string", "enum": ["consistent", "contradictory", "evidence_unavailable", "not_applicable"], "description": "Compare the recommendation with the rationale; use evidence_unavailable only when the relevant policy source is absent or unavailable."},
                },
                "required": ["recommendation", "rationale", "consistency"],
                "additionalProperties": False,
            },
            "findings": {"type": "array", "maxItems": 3, "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "finding": {"type": "string", "minLength": 1, "maxLength": 300},
                    "evidence_ref": {"type": ["string", "null"]},
                    "classification": {"type": "string", "enum": ["unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other"], "description": "The actual issue established by the supplied evidence."},
                    "claim_field": {"type": "string", "enum": ["recommendation", "rationale", "policy_basis", "multiple", "evidence"], "description": "The Worker field or evidence item containing the issue."},
                },
                "required": ["severity", "finding", "evidence_ref", "classification", "claim_field"],
                "additionalProperties": False,
            }},
            "missing_information": {"type": "array", "maxItems": 3, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
            "recommendations": {"type": "array", "maxItems": 3, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
        },
        "required": ["action", "claim_assessment", "findings", "missing_information", "recommendations"],
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
        "Do not repeat the plan, criteria, constraints, or request. Return only the required output object."
    ),
    "reviewer": (
        "You are the Reviewer. Check the model-generated Planner tasks and Worker result against supplied evidence. "
        "Review application-enforced criteria as requirements, not as Planner work. "
        "The complete contents of every evidence item are included below. Read those contents before making a finding. "
        "Use each item's stated meaning: customer facts establish stored customer fields; MCP profile evidence validates "
        "profile completeness and tier validity only; loyalty policy evidence establishes approved benefit rules. "
        "Do not call information missing if it is present in an available evidence item. Do not treat MCP profile "
        "validation as reward policy. Compare each factual Worker claim with the matching source, including tier and benefit wording. "
        "Audit the recommendation, rationale, and policy_basis as separate claims, then compare them with each other. "
        "A material benefit stated in one field but denied or contradicted in another is a contradiction, even if one field "
        "quotes the policy accurately. Compare amounts and benefit types exactly with the matching policy section; do not "
        "treat a different amount as supported just because the policy permits a related benefit. Mark a claim supported "
        "only when the relevant source establishes the full benefit and amount stated; a related or smaller permitted benefit "
        "does not support a different amount, and the Worker's own assertion is not evidence. For each unsupported claim, "
        "name that claim and cite the available policy evidence that fails to support it. Distinguish a supported benefit, "
        "an unsupported benefit, and a contradiction between the recommendation and rationale. "
        "Only classify policy evidence as unavailable when it is absent or its status is not available; do not call supplied "
        "policy text unavailable merely because the claim conflicts with it. "
        "Before saying a claim is absent from the Worker result, check all three Worker fields; a claim present in any one "
        "of those fields is not missing from the Worker output. "
        "In claim_assessment, independently classify each of the recommendation and rationale as supported, unsupported, "
        "evidence_unavailable, or not_applicable. Supported means the evidence establishes the complete claim; unsupported "
        "means the available evidence does not establish the claim. Set consistency to contradictory only when the recommendation and "
        "rationale make incompatible claims; use evidence_unavailable when the missing source prevents that comparison. "
        "A supplied policy that contradicts a benefit claim means the claim is unsupported, not that the policy is unavailable. "
        "When the policy is unavailable, classify the benefit recommendation as evidence_unavailable. A rationale that "
        "accurately reports the failed retrieval can be supported by the evidence status, even though the benefit itself cannot be checked. "
        "Keep each finding's classification, claim_field, and claim_assessment consistent: an unsupported_claim finding "
        "for recommendation or rationale requires that field's assessment to be unsupported; a contradiction finding "
        "requires consistency=contradictory and at least one of those claims to be unsupported. "
        "A finding must name a specific claim and evidence that contradicts or fails to support it. Only list information "
        "required by the goal that is absent from available evidence as missing. If evidence supports the material claims "
        "and there are no defects, return no findings and no missing information. "
        "Identify unsupported claims, defects, risks and missing information. Choose ready_for_human when material Worker claims "
        "are supported and there are no unresolved problems. Choose not_supported only when findings or missing_information "
        "state a concrete unresolved problem. Choose revise when a specific correction is needed. "
        "The action field contains that decision code; recommendations contains human-readable next steps, never an action code. "
        "Treat a statement as unsupported when the referenced evidence does not establish it. "
        "Keep findings and recommendations concise and use the minimum necessary entries. "
        "Return only the required output object; do not repeat supplied inputs."
    ),
}


def _model_output_schema(role, prompt):
    """Constrain model evidence references to the IDs in the current request."""
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
        schema["properties"]["findings"]["items"]["properties"]["evidence_ref"]["enum"] = evidence_ids + [None]
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


def _call_model(role, prompt):
    model = ROLE_MODELS[role]
    available = _available_models(timeout=min(STAGE_TIMEOUT, 10))
    if model not in available:
        raise WorkflowError("configured {} model '{}' is unavailable; available models: {}".format(
            role, model, ", ".join(available) or "none"
        ))
    payload = {
        "model": model,
        "prompt": prompt,
        "system": ROLE_INSTRUCTIONS[role],
        "format": _model_output_schema(role, prompt),
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0.2, "num_predict": NUM_PREDICT, "num_ctx": CONTEXT_SIZE},
    }
    if model.startswith("deepseek-r1"):
        # DeepSeek R1 otherwise spends the constrained JSON output budget on a
        # private reasoning trace before emitting the required object.
        payload["think"] = False
    response = requests.post(OLLAMA_URL + "/api/generate", json=payload, timeout=STAGE_TIMEOUT)
    response.raise_for_status()
    model_response = response.json()
    raw = model_response.get("response", "")
    try:
        output = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise WorkflowError("{} returned malformed JSON (done_reason={}, eval_count={})".format(
            role, model_response.get("done_reason", "unknown"), model_response.get("eval_count", "unknown")
        )) from exc
    if not isinstance(output, dict):
        raise WorkflowError("{} output must be a JSON object".format(role))
    return model, output


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
        "rationale": _required_text(output.get("rationale"), "rationale", 600),
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


def _reviewer_output(output, evidence, worker_result=None, request_data=None):
    """Validate reviewer structure while preserving its actual findings and action."""
    evidence_ids = {item["id"] for item in evidence}
    action = output.get("action")
    if action not in ("ready_for_human", "revise", "not_supported"):
        raise WorkflowError("Reviewer action must be ready_for_human, revise, or not_supported")

    claim_assessment = output.get("claim_assessment")
    if claim_assessment is not None:
        allowed = {
            "recommendation": {"supported", "unsupported", "evidence_unavailable", "not_applicable"},
            "rationale": {"supported", "unsupported", "evidence_unavailable", "not_applicable"},
            "consistency": {"consistent", "contradictory", "evidence_unavailable", "not_applicable"},
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
            if available_policy_ids and "evidence_unavailable" in claim_assessment.values():
                raise WorkflowError("Reviewer classified available policy evidence as unavailable")
            if not available_policy_ids and claim_assessment["recommendation"] != "evidence_unavailable":
                raise WorkflowError("Reviewer did not classify the policy-dependent recommendation as evidence_unavailable")

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
            **({
                "classification": item["classification"],
                "claim_field": item["claim_field"],
            } if item.get("classification") in ("unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other")
              and item.get("claim_field") in ("recommendation", "rationale", "policy_basis", "multiple", "evidence") else {}),
        })
        if claim_assessment is not None and (
            item.get("classification") not in ("unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other")
            or item.get("claim_field") not in ("recommendation", "rationale", "policy_basis", "multiple", "evidence")
        ):
            raise WorkflowError("Reviewer finding must classify its issue and Worker field")

    if claim_assessment is not None:
        for finding in clean_findings:
            classification, field = finding.get("classification"), finding.get("claim_field")
            if classification == "contradiction" and claim_assessment["consistency"] != "contradictory":
                raise WorkflowError("Reviewer finding and claim_assessment disagree about a contradiction")
            if (classification == "contradiction"
                    and claim_assessment["recommendation"] != "unsupported"
                    and claim_assessment["rationale"] != "unsupported"):
                raise WorkflowError("Reviewer contradiction finding has no unsupported Worker claim")
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

    missing_information = _string_list(output.get("missing_information", []), "missing_information")
    recommendations = _string_list(output.get("recommendations", []), "recommendations")
    if action == "not_supported" and not findings and not missing_information:
        raise WorkflowError("Reviewer returned not_supported without a concrete finding or missing-information item")
    if any(item in ("ready_for_human", "revise", "not_supported") for item in recommendations):
        raise WorkflowError("Reviewer put an action code in recommendations instead of the action field")
    unavailable = [item for item in evidence if item.get("status") != "available"]
    if unavailable:
        action = "not_supported"
        for item in unavailable:
            missing_information.append("{} evidence is {} and cannot support the recommendation.".format(
                item["id"], item.get("status", "unavailable")
            ))
            clean_findings.append({
                "severity": "high",
                "finding": "{} evidence was {} and was excluded from Worker support.".format(
                    item["id"], item.get("status", "unavailable")
                ),
                "evidence_ref": item["id"],
                "classification": "missing_evidence",
                "claim_field": "evidence",
            })

    result = {
        "action": action,
        "findings": clean_findings,
        "missing_information": missing_information,
        "recommendations": recommendations,
    }
    if claim_assessment is not None:
        result["claim_assessment"] = {field: claim_assessment[field] for field in allowed}
    return result


def _prompt(role, request_data, evidence, plan=None, worker=None, findings=None, revision=0):
    if role == "planner":
        # Keep application-owned criteria out of the model-generated plan.
        role_request = {"goal": request_data.get("goal")}
        role_evidence = evidence
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
        role_evidence = evidence

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
        sections.append("WORKER RESULT:\n" + json.dumps(worker, ensure_ascii=False))
    if findings is not None:
        sections.append("REVIEW FINDINGS TO ADDRESS:\n" + json.dumps(findings, ensure_ascii=False))
    if role == "worker":
        sections.append("REVISION NUMBER: {}".format(revision))
    return "\n\n".join(sections)


def _call_validated(workflow, role, prompt, validate):
    """Call one role and validate its output, retrying with the rejection reason fed back.

    Returns (model, validated output). Raises StageOutputRejected, carrying the
    last raw output, when every attempt is rejected.
    """
    error, raw = None, None
    for attempt in range(1, STAGE_ATTEMPTS + 1):
        attempt_prompt = prompt
        if error is not None:
            attempt_prompt += (
                "\n\nYOUR PREVIOUS OUTPUT WAS REJECTED: {}\n"
                "Return a corrected object that satisfies every rule above.".format(error)
            )
        try:
            model, raw = _call_model(role, attempt_prompt)
            return model, validate(raw)
        except (WorkflowError, ValueError, KeyError, TypeError) as exc:
            error = str(exc)[:300]
            _save(workflow, "stage_output_rejected", {"role": role, "attempt": attempt, "error": error})
    raise StageOutputRejected(role, error, raw)


def _reconciled_review(raw, evidence, request_data, error):
    """Conservative Reviewer result when its output stayed internally inconsistent.

    Nothing is upgraded: every Worker claim is treated as unsupported, the
    Reviewer's own findings are kept for the human, and the inconsistency is
    recorded as a high-severity finding.
    """
    raw = raw if isinstance(raw, dict) else {}
    evidence_ids = {item["id"] for item in evidence}
    classifications = ("unsupported_claim", "contradiction", "missing_evidence", "source_misuse", "other")
    fields = ("recommendation", "rationale", "policy_basis", "multiple", "evidence")
    findings = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict) or not isinstance(item.get("finding"), str) or not item["finding"].strip():
            continue
        findings.append({
            "severity": item.get("severity") if item.get("severity") in ("low", "medium", "high") else "medium",
            "finding": item["finding"].strip()[:300],
            "evidence_ref": item.get("evidence_ref") if item.get("evidence_ref") in evidence_ids else None,
            "classification": item.get("classification") if item.get("classification") in classifications else "other",
            "claim_field": item.get("claim_field") if item.get("claim_field") in fields else "multiple",
        })
    findings = findings[:3] + [{
        "severity": "high",
        "finding": "Reviewer output stayed internally inconsistent after {} attempts ({}); "
                   "treat every Worker claim as unchecked.".format(STAGE_ATTEMPTS, error)[:300],
        "evidence_ref": None,
        "classification": "other",
        "claim_field": "multiple",
    }]

    def strings(key):
        values = raw.get(key) if isinstance(raw.get(key), list) else []
        return [value.strip()[:160] for value in values if isinstance(value, str) and value.strip()][:3]

    policy_ids = set((request_data or {}).get("worker_policy_evidence_ids", []))
    policy_available = any(item["id"] in policy_ids and item.get("status") == "available" for item in evidence)
    missing_information = strings("missing_information")
    for item in evidence:
        if item.get("status") != "available":
            missing_information.append("{} evidence is {} and cannot support the recommendation.".format(
                item["id"], item.get("status", "unavailable")
            ))
    return {
        "action": "not_supported",
        "claim_assessment": {
            "recommendation": "unsupported" if policy_available or not policy_ids else "evidence_unavailable",
            "rationale": "unsupported",
            "consistency": "not_applicable",
        },
        "findings": findings,
        "missing_information": missing_information,
        "recommendations": strings("recommendations") or [
            "Check the Worker recommendation against the evidence before deciding."
        ],
        "reconciled": True,
        "validation_error": error,
    }


def _run_workflow(workflow_id):
    workflow = _history(workflow_id=workflow_id)[0]
    evidence_ids = {item["id"] for item in workflow["evidence"]}
    available_evidence_ids = {item["id"] for item in workflow["evidence"] if item["status"] == "available"}
    allowed_worker_ids = workflow["request"].get("worker_evidence_ids")
    if allowed_worker_ids is not None:
        available_evidence_ids &= set(allowed_worker_ids)

    def planner_result(raw):
        plan = _planner_output(raw, evidence_ids, workflow["request"])
        if not _plan_is_complete(plan, evidence_ids, workflow["request"]):
            raise WorkflowError("Planner did not produce a complete required plan")
        return plan

    def worker_result(raw):
        result = _worker_output(raw, available_evidence_ids)
        return _validate_worker_contract(result, workflow["evidence"], workflow["request"])

    try:
        workflow["status"], workflow["stage"] = "planning", "planner"
        _save(workflow, "stage_started", {"role": "planner", "model": ROLE_MODELS["planner"]})
        model, workflow["plan"] = _call_validated(
            workflow, "planner", _prompt("planner", workflow["request"], workflow["evidence"]), planner_result,
        )
        workflow["roles"].append({"role": "planner", "model": model, "completed_at": _now()})
        _save(workflow, "stage_completed", {"role": "planner", "model": model, "plan": workflow["plan"]})

        for revision in range(workflow["max_revisions"] + 1):
            workflow["status"], workflow["stage"] = ("revising" if revision else "working"), "worker"
            _save(workflow, "stage_started", {"role": "worker", "revision": revision, "model": ROLE_MODELS["worker"]})
            model, workflow["worker_result"] = _call_validated(workflow, "worker", _prompt(
                "worker", workflow["request"], workflow["evidence"], workflow["plan"],
                workflow.get("worker_result"),
                (workflow.get("reviewer_result") or {}).get("findings"), revision,
            ), worker_result)
            workflow["roles"].append({"role": "worker", "model": model, "revision": revision, "completed_at": _now()})
            _save(workflow, "stage_completed", {"role": "worker", "revision": revision, "result": workflow["worker_result"]})

            workflow["status"], workflow["stage"] = "reviewing", "reviewer"
            _save(workflow, "stage_started", {"role": "reviewer", "model": ROLE_MODELS["reviewer"]})
            try:
                model, workflow["reviewer_result"] = _call_validated(workflow, "reviewer", _prompt(
                    "reviewer", workflow["request"], workflow["evidence"], workflow["plan"],
                    workflow["worker_result"], revision=revision,
                ), lambda raw: _reviewer_output(
                    raw, workflow["evidence"], workflow["worker_result"], workflow["request"]
                ))
            except StageOutputRejected as exc:
                if exc.raw is None:
                    raise
                # The Reviewer answered but contradicted itself: hand its findings
                # to the human as unchecked rather than discarding the workflow.
                model = ROLE_MODELS["reviewer"]
                workflow["reviewer_result"] = _reconciled_review(
                    exc.raw, workflow["evidence"], workflow["request"], exc.error,
                )
                _save(workflow, "reviewer_output_reconciled", {"error": exc.error})
            workflow["roles"].append({"role": "reviewer", "model": model, "completed_at": _now()})
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
