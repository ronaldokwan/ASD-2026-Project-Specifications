"""AI-Mode microservice (shared by the whole team).

Exposes the Plan -> Act -> Observe -> Adapt loop over HTTP so that every
student backend/API microservice reaches the approved open-source LLM through
one common, auditable path:

    frontend -> backend/API -> AI-Mode -> Ollama -> LLM

Endpoints
    GET  /health      liveness plus Ollama/model readiness
    GET  /config      how the agentic loop is configured
    POST /agent/run   run the agentic loop for one caller request
"""

import os
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

from agent import AgentRequest, AgenticLoop
from agent.ollama_client import OllamaClient, OllamaError
from agent import review_modes
from agent.validators import MCP_VALIDATION_SCHEMA, RAG_VALIDATION_SCHEMA

app = Flask(__name__)

_review_lock = threading.RLock()
_review_dir = Path(os.getenv(
    "AI_MODE_REVIEW_DATA_DIR",
    str(Path(__file__).resolve().parents[2] / "reports" / "agentic-reviews"),
))
_review_history = _review_dir / "review_history.jsonl"
_validation_log = _review_dir / "review_validation.jsonl"


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
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    return value


def _append_review(record):
    _review_dir.mkdir(parents=True, exist_ok=True)
    with _review_lock:
        for path in (_review_history, _validation_log):
            item = dict(record)
            if path == _validation_log:
                item = {key: value for key, value in record.items()
                        if key in ("at", "review_id", "mode", "validation_log")}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_redact(item), ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()

client = OllamaClient()
loop = AgenticLoop(client=client)

# Validation modes reuse the agentic loop with mode-specific schemas and
# deterministic fallbacks for MCP tool results and RAG answers.
_VALIDATION_MODES = {
    "mcp": {
        "goal": "mcp_validation",
        "task": (
            "You are reviewing the result of a tool call made by a retail microservice. "
            "Check whether the structured result below is plausible, internally consistent, "
            "and actually answers what the tool was asked to do. When valid is true, notes "
            "must not invent missing fields, warnings, errors, or failures. When valid is "
            "false, notes must identify the actual contract problem or reported error. "
            "Do not invent new facts and do not re-run the tool yourself."
        ),
        "schema": MCP_VALIDATION_SCHEMA,
        "fallback": {
            "valid": "false",
            "notes": "The tool result was not validated because AI-Mode was unavailable.",
            "confidence": "low",
        },
    },
    "rag": {
        "goal": "rag_validation",
        "task": (
            "You are reviewing a grounded answer produced by a retrieval-augmented system. "
            "Check whether every claim in the answer is actually supported by the sources "
            "provided, and whether the claimed confidence category is justified by how many "
            "sources support it. The verdict fields must agree: when grounded is true, "
            "unsupported_claims must be exactly 'none'; when grounded is false, "
            "unsupported_claims must identify the unsupported claim or contradiction. "
            "Do not invent new facts."
        ),
        "schema": RAG_VALIDATION_SCHEMA,
        "fallback": {
            "grounded": "false",
            "unsupported_claims": (
                "Grounding could not be verified because validation was unavailable."
            ),
            "confidence_ok": "false",
            "notes": (
                "The answer is not confirmed as supported because AI-Mode validation "
                "was unavailable."
            ),
        },
    },
}


@app.get("/health")
def health():
    try:
        models = client.available_models()
        ollama_up = True
    except OllamaError as exc:
        models, ollama_up = [], False
        app.logger.warning("Ollama health check failed: %s", exc)

    return jsonify({
        "service": "ai-mode",
        "status": "ok" if ollama_up else "degraded",
        "ollama_url": client.base_url,
        "ollama_reachable": ollama_up,
        "model": client.model,
        "model_pulled": any(m.split(":")[0] == client.model.split(":")[0] for m in models),
        "models_available": models,
    }), (200 if ollama_up else 503)


@app.get("/config")
def config():
    """How the shared agentic loop is currently configured."""
    return jsonify({
        "workflow": ["Plan", "Act", "Observe", "Adapt"],
        "max_adapt_attempts": loop.max_attempts,
        "model": client.model,
        "ollama_url": client.base_url,
    })


@app.post("/agent/run")
def agent_run():
    try:
        agent_request = AgentRequest.from_json(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    outcome = loop.run(agent_request)
    return jsonify(outcome), (200 if outcome["ok"] else 502)


@app.post("/agent/validate")
def agent_validate():
    """Validate tool/RAG output or review workflow/test/deployment evidence.

    Body: {"mode": <supported mode>, "subject": {...}}.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "request body must be a JSON object"}), 400

    mode = payload.get("mode")
    spec = _VALIDATION_MODES.get(mode)
    report_review = mode in review_modes.REVIEW_MODES
    if report_review:
        spec = {
            "goal": review_modes.REVIEW_MODES[mode]["goal"],
            "task": review_modes.task_for(mode),
            "schema": review_modes.schema_for(mode),
            "fallback": {
                "assessment": "incomplete",
                **{field: "The model review did not execute." for field in review_modes.REVIEW_MODES[mode]["dimensions"]},
                "findings": "No model findings were produced.",
                "risks": "Evidence remains unverified without model execution.",
                "recommendations": "Review the evidence and retry when the model service is available.",
            },
        }
    if not spec:
        return jsonify({
            "ok": False,
            "error": "'mode' must be one of: {}".format(
                ", ".join(list(_VALIDATION_MODES) + list(review_modes.REVIEW_MODES))
            ),
        }), 400

    subject = payload.get("subject")
    if not isinstance(subject, dict) or not subject:
        return jsonify({"ok": False, "error": "'subject' is required and must be a non-empty object"}), 400

    agent_request = AgentRequest(
        goal=spec["goal"],
        task=spec["task"],
        context=subject,
        output_schema=spec["schema"],
        fallback=spec["fallback"],
        mode="{}_validation".format(mode),
    )
    outcome = loop.run(agent_request)
    if report_review:
        outcome = review_modes.finalize_review(mode, subject, outcome)
        at = datetime.now(timezone.utc).isoformat()
        record = {
            "at": at,
            "review_id": outcome["review_id"],
            "mode": mode,
            "model": outcome.get("model"),
            "model_reviewed": outcome["result"]["validation_log"]["model_reviewed"],
            "subject_summary": _review_subject_summary(mode, subject),
            "result": outcome["result"],
            "validation_log": outcome["result"]["validation_log"],
        }
        _append_review(record)
        return jsonify(outcome), (200 if outcome.get("ok") else 502)
    return jsonify(outcome), (200 if outcome["ok"] else 502)


def _review_subject_summary(mode, subject):
    """Keep report logs useful without copying source code, reports or credentials."""
    if mode == "testing_report":
        security = subject.get("pre_commit_security_results") if isinstance(subject.get("pre_commit_security_results"), list) else []
        endpoint_tests = subject.get("post_commit_backend_endpoint_tests") if isinstance(subject.get("post_commit_backend_endpoint_tests"), list) else []
        hosted_ci = subject.get("hosted_ci") if isinstance(subject.get("hosted_ci"), dict) else {}
        return {
            "test_code_supplied": isinstance(subject.get("test_code"), str) and bool(subject["test_code"].strip()),
            "pre_commit_security_results": [{"name": item.get("name"), "status": item.get("status"),
                                              "exit_code": item.get("exit_code")}
                                             for item in security if isinstance(item, dict)],
            "post_commit_backend_endpoint_tests": [{"endpoint": item.get("endpoint"),
                                                    "test_ref": item.get("test_ref"),
                                                    "phase": item.get("phase"),
                                                    "origin": item.get("origin", "local"),
                                                    "status": item.get("status"),
                                                    "exit_code": item.get("exit_code")}
                                                   for item in endpoint_tests if isinstance(item, dict)],
            "hosted_ci": {"status": hosted_ci.get("status"), "run_id": hosted_ci.get("run_id")},
        }
    if mode == "cloud_deployment_report":
        resources = subject.get("infrastructure_evidence") if isinstance(subject.get("infrastructure_evidence"), list) else []
        checks = subject.get("runtime_checks") if isinstance(subject.get("runtime_checks"), list) else []
        return {
            "infrastructure_evidence": [{"name": item.get("name"), "status": item.get("status")}
                                         for item in resources if isinstance(item, dict)],
            "runtime_checks": [{"check": item.get("check"), "status": item.get("status"),
                                "http_status": item.get("http_status")}
                               for item in checks if isinstance(item, dict)],
        }
    workflow = subject.get("workflow")
    if isinstance(workflow, dict):
        return {"workflow_id": workflow.get("workflow_id"), "status": workflow.get("status"),
                "completion_gate": workflow.get("completion_gate")}
    return {"subject_keys": sorted(str(key) for key in subject.keys())[:30]}


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7000")), debug=False)
