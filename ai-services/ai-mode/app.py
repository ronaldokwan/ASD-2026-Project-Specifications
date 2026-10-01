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

from flask import Flask, jsonify, request

from agent import AgentRequest, AgenticLoop
from agent.ollama_client import OllamaClient, OllamaError
from agent.validators import MCP_VALIDATION_SCHEMA, RAG_VALIDATION_SCHEMA

app = Flask(__name__)

client = OllamaClient()
loop = AgenticLoop(client=client)

# Release 1: the two extra "validation modes" of the shared agentic loop. Each
# builds an AgentRequest around the *subject* the caller supplies (an MCP tool
# result, or a RAG answer + its sources) and runs it through the same
# Plan -> Act -> Observe -> Adapt loop used for chat, so a validation verdict
# gets the same guardrails/fallback safety net as every other AI-Mode answer.
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
    """Release 1: MCP and RAG validation modes of the shared agentic loop.

    Body: {"mode": "mcp"|"rag", "subject": {...}}. ``subject`` is whatever the
    caller wants double-checked - an MCP tool call + its result, or a RAG
    query + answer + sources - and is handed to the model as context.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "request body must be a JSON object"}), 400

    mode = payload.get("mode")
    spec = _VALIDATION_MODES.get(mode)
    if not spec:
        return jsonify({
            "ok": False,
            "error": "'mode' must be one of: {}".format(", ".join(_VALIDATION_MODES)),
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
    return jsonify(outcome), (200 if outcome["ok"] else 502)


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7000")), debug=True)
