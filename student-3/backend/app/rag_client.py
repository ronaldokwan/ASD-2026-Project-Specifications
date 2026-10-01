"""Validated HTTP client for Customer Account loyalty-policy RAG."""

import requests

from .config import Config


class RAGServiceUnavailable(RuntimeError):
    """The RAG service or its local model is unavailable."""


class RAGBadResponse(RuntimeError):
    """The RAG service returned a malformed response."""


def _validate_sources(sources):
    if not isinstance(sources, list):
        raise RAGBadResponse("RAG sources must be a list")
    cleaned = []
    for source in sources:
        if not isinstance(source, dict):
            raise RAGBadResponse("each RAG source must be an object")
        for field in ("source", "section", "snippet"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise RAGBadResponse("RAG source {} is missing".format(field))
        cleaned.append({
            "source": source["source"],
            "section": source["section"],
            "snippet": source["snippet"],
        })
    return cleaned


def _validate_response(body):
    if not isinstance(body, dict):
        raise RAGBadResponse("RAG response must be an object")
    status = body.get("status")
    if status == "insufficient_context":
        if body.get("answer", "") != "" or body.get("sources") != []:
            raise RAGBadResponse("insufficient-context response contains an answer or sources")
        if body.get("confidence") != "insufficient" or not isinstance(body.get("message"), str):
            raise RAGBadResponse("insufficient-context response is malformed")
        return {
            "status": status,
            "answer": "",
            "sources": [],
            "confidence": "insufficient",
            "message": body["message"],
        }
    if status != "ok":
        raise RAGBadResponse("RAG response has an unsupported status")
    if not isinstance(body.get("answer"), str) or not body["answer"].strip():
        raise RAGBadResponse("RAG answer is missing")
    if body.get("confidence") not in ("high", "medium", "low"):
        raise RAGBadResponse("RAG confidence is invalid")
    sources = _validate_sources(body.get("sources"))
    if not sources:
        raise RAGBadResponse("grounded RAG answer has no sources")
    return {
        "status": "ok",
        "answer": body["answer"],
        "sources": sources,
        "confidence": body["confidence"],
    }


def ask_loyalty_benefits(question):
    if not Config.RAG_ENABLED:
        raise RAGServiceUnavailable("RAG integration is disabled")
    url = "{}/rag/query".format(Config.RAG_SERVER_URL)
    payload = {
        "query": question,
        "top_k": 5,
        "filters": {"feature": "customer_accounts"},
    }
    try:
        response = requests.post(url, json=payload, timeout=Config.RAG_TIMEOUT)
    except requests.Timeout as exc:
        raise RAGServiceUnavailable("RAG request timed out") from exc
    except requests.RequestException as exc:
        raise RAGServiceUnavailable("RAG server is unreachable at {}".format(url)) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise RAGBadResponse("RAG server returned non-JSON data") from exc
    if response.status_code == 503 or body.get("status") == "service_unavailable":
        raise RAGServiceUnavailable(body.get("message", "RAG generation is unavailable"))
    if response.status_code >= 500:
        raise RAGServiceUnavailable("RAG server returned {}".format(response.status_code))
    if response.status_code >= 400:
        raise RAGBadResponse(body.get("error", "RAG request was rejected"))
    return _validate_response(body)
