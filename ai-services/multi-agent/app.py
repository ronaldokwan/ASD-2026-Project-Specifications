"""Multi-Agent microservice (shared by the whole team).

Coordinates the Planner, Worker and Reviewer agents, then records the human
review decision that always has the final word:

    frontend -> backend/API -> Multi-Agent Server -> Planner -> Worker -> Reviewer -> Human Review

Endpoints
    GET  /health                          liveness plus Ollama/model readiness
    GET  /config                          how the workflow is configured
    POST /workflow/run                    run Planner -> Worker -> Reviewer for one request
    GET  /workflow                        recent workflow history (audit trail)
    GET  /workflow/<id>                   one workflow record
    POST /workflow/<id>/human-review      record the human approve/correct/partial_accept/reject
"""

import os
import uuid

from flask import Flask, jsonify, request

from agent import store
from agent.ollama_client import OllamaClient, OllamaError
from agent.workflow import HUMAN_DECISIONS, MultiAgentWorkflow, WorkflowRequest

app = Flask(__name__)

client = OllamaClient()
workflow = MultiAgentWorkflow(client=client)


@app.get("/health")
def health():
    try:
        models = client.available_models()
        ollama_up = True
    except OllamaError as exc:
        models, ollama_up = [], False
        app.logger.warning("Ollama health check failed: %s", exc)

    return jsonify({
        "service": "multi-agent",
        "status": "ok" if ollama_up else "degraded",
        "ollama_url": client.base_url,
        "ollama_reachable": ollama_up,
        "model": client.model,
        "model_pulled": any(m.split(":")[0] == client.model.split(":")[0] for m in models),
        "models_available": models,
    }), (200 if ollama_up else 503)


@app.get("/config")
def config():
    """How the shared Multi-Agent workflow is currently configured."""
    return jsonify({
        "workflow": ["Planner", "Worker", "Reviewer", "Human Review"],
        "human_decisions": list(HUMAN_DECISIONS),
        "model": client.model,
        "ollama_url": client.base_url,
    })


@app.post("/workflow/run")
def workflow_run():
    """Run Planner -> Worker -> Reviewer for one request from a student backend."""
    try:
        wf_request = WorkflowRequest.from_json(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    outcome = workflow.run(wf_request)
    workflow_id = uuid.uuid4().hex[:12]
    record = store.create(workflow_id, outcome)
    return jsonify(record), 200


@app.get("/workflow")
def workflow_list():
    """Recent workflow history - the coordination/audit trail for the report."""
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"workflows": store.list_recent(limit)})


@app.get("/workflow/<workflow_id>")
def workflow_get(workflow_id):
    record = store.get(workflow_id)
    if record is None:
        return jsonify({"ok": False, "error": "workflow not found"}), 404
    return jsonify(record)


@app.post("/workflow/<workflow_id>/human-review")
def workflow_human_review(workflow_id):
    """Record the human's approval, correction, partial acceptance or rejection."""
    record = store.get(workflow_id)
    if record is None:
        return jsonify({"ok": False, "error": "workflow not found"}), 404
    if record["status"] != "pending_human_review":
        return jsonify({
            "ok": False,
            "error": "workflow already has a human decision: {}".format(record["status"]),
        }), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "request body must be a JSON object"}), 400

    decision = payload.get("decision")
    if decision not in HUMAN_DECISIONS:
        return jsonify({
            "ok": False,
            "error": "'decision' must be one of: {}".format(", ".join(HUMAN_DECISIONS)),
        }), 400

    corrected_result = payload.get("corrected_result")
    if decision == "reject":
        final_result = None
    elif decision in ("correct", "partial_accept") and isinstance(corrected_result, dict):
        final_result = corrected_result
    else:
        final_result = record["worker"]["result"]

    status = {
        "approve": "approved",
        "correct": "corrected",
        "partial_accept": "partially_accepted",
        "reject": "rejected",
    }[decision]

    human_review = {
        "decision": decision,
        "comment": str(payload.get("comment") or "").strip(),
        "reviewer": str(payload.get("reviewer") or "").strip() or "unspecified",
    }

    record = store.update_human_review(workflow_id, human_review, final_result, status)
    return jsonify(record)


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7004")), debug=True)
