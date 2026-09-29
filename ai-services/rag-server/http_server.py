"""HTTP front door for the shared RAG server.

This is the "shared non-containerised local RAG server" every feature's
backend/API calls directly, per the Release 1 brief: retrieve relevant
context, generate a grounded answer with the local LLM, and return source
citations and a confidence category - or an explicit insufficient-context
result when nothing relevant was found.

Endpoints
    GET    /health                liveness
    POST   /rag/documents         upsert one or more documents into the shared corpus
    DELETE /rag/documents/<id>    remove a document from the shared corpus
    POST   /rag/query             retrieve + generate a grounded, cited answer
"""

import os

from flask import Flask, jsonify, request

from rag_pipeline import answer_question, delete_document, upsert_documents

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"service": "rag-server", "status": "ok", "model": os.getenv("LLM_MODEL", "qwen2.5:0.5b")})


@app.post("/rag/documents")
def add_documents():
    payload = request.get_json(silent=True) or {}
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        return jsonify({"ok": False, "error": "'documents' must be a non-empty list"}), 400
    for doc in documents:
        if not isinstance(doc, dict) or not doc.get("id") or not doc.get("text"):
            return jsonify({"ok": False, "error": "each document needs an 'id' and 'text'"}), 400

    return jsonify(upsert_documents(documents))


@app.delete("/rag/documents/<doc_id>")
def remove_document(doc_id):
    return jsonify(delete_document(doc_id))


@app.post("/rag/query")
def query():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("query") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "'query' is required"}), 400

    top_k = int(payload.get("top_k", 5))
    filters = payload.get("filters") or None
    result = answer_question(question, top_k=top_k, filters=filters)
    return jsonify(result)


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "endpoint not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SERVICE_PORT", "7003")), debug=True)
