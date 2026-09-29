"""HTTP front door for the shared MCP server.

Student backends run inside Docker and need to call a tool synchronously
within one request/response cycle, which the MCP stdio transport in
``server.py`` isn't built for. This Flask app exposes the same tool
functions from ``tools.py`` as plain JSON endpoints instead - the "shared
non-containerised local MCP server" every feature's backend/API talks to.

Endpoints
    GET  /health                          liveness
    GET  /tools                           list the tools this server exposes
    POST /tools/check_review_quality      run Student 5's moderation tool
"""

import os

from flask import Flask, jsonify, request

from tools import check_review_quality

app = Flask(__name__)

TOOL_CONTRACTS = {
    "check_review_quality": {
        "description": "Deterministic moderation check for one product review.",
        "required": ["review_text", "rating"],
        "optional": ["existing_review_count", "average_rating"],
    },
}


@app.get("/health")
def health():
    return jsonify({"service": "mcp-server", "status": "ok", "tools": list(TOOL_CONTRACTS)})


@app.get("/tools")
def list_tools():
    return jsonify({"tools": TOOL_CONTRACTS})


@app.post("/tools/check_review_quality")
def run_check_review_quality():
    payload = request.get_json(silent=True) or {}
    if "review_text" not in payload or "rating" not in payload:
        return jsonify({"ok": False, "error": "'review_text' and 'rating' are required"}), 400

    result = check_review_quality(
        review_text=payload.get("review_text"),
        rating=payload.get("rating"),
        existing_review_count=payload.get("existing_review_count", 0),
        average_rating=payload.get("average_rating"),
    )
    return jsonify({"ok": True, "tool": "check_review_quality", "result": result})


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7002")), debug=True)
