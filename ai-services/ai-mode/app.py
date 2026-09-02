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

app = Flask(__name__)

client = OllamaClient()
loop = AgenticLoop(client=client)


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


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7000")), debug=True)
