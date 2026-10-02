"""Legacy Flask compatibility facade for the shared MCP tools.

The normal startup path now runs ``server.py`` with genuine MCP Streamable
HTTP at ``/mcp``. That server also co-hosts the Student 5 compatibility REST
route. This module remains only for backward-compatible direct Flask tests or
manual use and is not an MCP protocol endpoint.

Endpoints
    GET  /health                          liveness
    GET  /tools                           list the tools this server exposes
    POST /tools/check_review_quality      run Student 5's moderation tool
    POST /tools/check_order_fulfilment    run Student 2's order-readiness tool
"""

import os

from flask import Flask, jsonify, request

from tools import check_order_fulfilment, check_review_quality

app = Flask(__name__)

TOOL_CONTRACTS = {
    "check_review_quality": {
        "description": "Deterministic moderation check for one product review.",
        "required": ["review_text", "rating"],
        "optional": ["existing_review_count", "average_rating"],
    },
    "check_order_fulfilment": {
        "description": "Deterministic shipment-readiness check for one order.",
        "required": [
            "order_number", "status", "line_count", "total_quantity",
            "order_total", "inventory_committed",
        ],
        "optional": [],
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


@app.post("/tools/check_order_fulfilment")
def run_check_order_fulfilment():
    payload = request.get_json(silent=True) or {}
    required = TOOL_CONTRACTS["check_order_fulfilment"]["required"]
    missing = [field for field in required if field not in payload]
    if missing:
        return jsonify({
            "ok": False,
            "error": "missing required field(s): {}".format(", ".join(missing)),
        }), 400

    result = check_order_fulfilment(
        order_number=payload.get("order_number"),
        status=payload.get("status"),
        line_count=payload.get("line_count"),
        total_quantity=payload.get("total_quantity"),
        order_total=payload.get("order_total"),
        inventory_committed=payload.get("inventory_committed"),
    )
    return jsonify({"ok": True, "tool": "check_order_fulfilment", "result": result})


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7002")), debug=True)
