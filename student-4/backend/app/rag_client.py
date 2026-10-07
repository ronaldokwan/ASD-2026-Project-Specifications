"""Client for the shared RAG corpus, scoped to inventory stock records."""

import logging
from urllib.parse import quote

import requests

from .config import Config

log = logging.getLogger(__name__)
_SYNC_TIMEOUT = (3, 15)
_synced = False
_CONFIDENCE = ("high", "medium", "low")


class RAGServiceUnavailable(RuntimeError):
    """The RAG server or its local model is disabled or unavailable."""


class RAGBadResponse(RuntimeError):
    """The RAG server returned a malformed response."""


def document_id(stock_id):
    return "inventory:stock:{}".format(stock_id)


def stock_document(stock):
    """Build a factual, citable document from one database record."""
    # Stable IDs let later updates replace the same record instead of duplicating it.
    text = (
        "{name} ({sku}) is a {category} inventory item. Current quantity is "
        "{quantity}; its restock threshold is {threshold}. It is stored at {location}."
    ).format(
        name=stock["name"],
        sku=stock["sku"],
        category=stock["category"],
        quantity=stock["quantity"],
        threshold=stock["restock_threshold"],
        location=stock["location"],
    )
    return {
        "id": document_id(stock["id"]),
        "text": text,
        "metadata": {
            "feature": Config.RAG_FEATURE,
            "source": "Inventory and Stock database",
            "section": "{} {}".format(stock["sku"], stock["name"]),
            "stock_id": stock["id"],
            "sku": stock["sku"],
            "category": stock["category"],
            "location": stock["location"],
        },
    }


def _post(path, payload, timeout=None):
    url = "{}{}".format(Config.RAG_SERVER_URL, path)
    try:
        response = requests.post(
            url, json=payload, timeout=timeout or (5, Config.RAG_TIMEOUT)
        )
    except requests.Timeout as exc:
        raise RAGServiceUnavailable("RAG request timed out") from exc
    except requests.RequestException as exc:
        raise RAGServiceUnavailable("RAG server is unreachable at {}".format(url)) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise RAGBadResponse("RAG server returned non-JSON data") from exc
    return response, body


def sync_stocks(stocks):
    """Index all inventory records; used by initial sync and the admin route."""
    global _synced
    if not Config.RAG_ENABLED:
        raise RAGServiceUnavailable("RAG integration is disabled")
    documents = [stock_document(stock) for stock in stocks]
    if not documents:
        _synced = True
        return {"ok": True, "documents_indexed": 0, "chunks_indexed": 0}
    response, body = _post(
        "/rag/documents", {"documents": documents}, timeout=_SYNC_TIMEOUT
    )
    if response.status_code >= 400 or not isinstance(body, dict) or not body.get("ok"):
        message = body.get("error", "RAG re-index was rejected") if isinstance(body, dict) else "RAG re-index was rejected"
        raise RAGBadResponse(message)
    _synced = True
    return body


def sync_stock(stock):
    """Upsert one stock record without failing its primary database write."""
    if not Config.RAG_ENABLED:
        return
    try:
        # RAG is a derived index; an indexing outage must not undo a saved stock change.
        response, body = _post(
            "/rag/documents",
            {"documents": [stock_document(stock)]},
            timeout=_SYNC_TIMEOUT,
        )
        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("ok"):
            raise RAGBadResponse("RAG rejected stock document update")
    except (RAGServiceUnavailable, RAGBadResponse) as exc:
        log.warning("RAG sync skipped for stock %s: %s", stock.get("id"), exc)


def remove_stock(stock_id):
    """Best-effort removal of a deleted stock document from the corpus."""
    if not Config.RAG_ENABLED:
        return
    url = "{}/rag/documents/{}".format(
        Config.RAG_SERVER_URL, quote(document_id(stock_id), safe="")
    )
    try:
        response = requests.delete(url, timeout=_SYNC_TIMEOUT)
        if response.status_code >= 400:
            log.warning("RAG rejected removal for stock %s", stock_id)
    except requests.RequestException as exc:
        log.warning("RAG removal skipped for stock %s: %s", stock_id, exc)


def ensure_synced(list_stocks):
    """Index the current inventory before the first question in this worker."""
    # Workers sync independently, so new processes can answer from the current inventory.
    if _synced:
        return
    try:
        sync_stocks(list_stocks())
    except (RAGServiceUnavailable, RAGBadResponse) as exc:
        log.warning("initial inventory RAG sync failed: %s", exc)


def _validate_sources(sources):
    if not isinstance(sources, list) or not sources:
        raise RAGBadResponse("grounded RAG answer has no sources")
    cleaned = []
    for source in sources:
        if not isinstance(source, dict):
            raise RAGBadResponse("each RAG source must be an object")
        for field in ("source", "section", "snippet"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise RAGBadResponse("RAG source {} is missing".format(field))
        metadata = source.get("metadata")
        # Never return a citation unless the RAG service confirms its feature ownership.
        if not isinstance(metadata, dict) or metadata.get("feature") != Config.RAG_FEATURE:
            raise RAGBadResponse("RAG cited a source outside Inventory and Stock")
        cleaned.append({
            "source": source["source"],
            "section": source["section"],
            "snippet": source["snippet"],
            "text": source.get("text") if isinstance(source.get("text"), str) else source["snippet"],
        })
    return cleaned


def _validate_response(body):
    if not isinstance(body, dict):
        raise RAGBadResponse("RAG response must be an object")
    if body.get("status") == "insufficient_context":
        if body.get("answer", "") != "" or body.get("sources") != [] or body.get("confidence") != "insufficient":
            raise RAGBadResponse("insufficient-context response is malformed")
        return {
            "status": "insufficient_context",
            "answer": "",
            "sources": [],
            "confidence": "insufficient",
            "message": body.get("message") or "Insufficient relevant context was found.",
        }
    if body.get("status") != "ok":
        raise RAGBadResponse("RAG response has an unsupported status")
    if not isinstance(body.get("answer"), str) or not body["answer"].strip():
        raise RAGBadResponse("RAG answer is missing")
    if body.get("confidence") not in _CONFIDENCE:
        raise RAGBadResponse("RAG confidence is invalid")
    return {
        "status": "ok",
        "answer": body["answer"].strip(),
        "sources": _validate_sources(body.get("sources")),
        "confidence": body["confidence"],
        "retrieved_count": body.get("retrieved_count"),
        "elapsed_ms": body.get("elapsed_ms"),
    }


def ask(question):
    """Ask one question, restricting retrieval and citations to inventory."""
    if not Config.RAG_ENABLED:
        raise RAGServiceUnavailable("RAG integration is disabled")
    # Apply the same feature tag at retrieval time as on each indexed document.
    response, body = _post("/rag/query", {
        "query": question,
        "top_k": Config.RAG_TOP_K,
        "filters": {"feature": Config.RAG_FEATURE},
    })
    if not isinstance(body, dict):
        raise RAGBadResponse("RAG response must be an object")
    if response.status_code == 503 or body.get("status") == "service_unavailable":
        raise RAGServiceUnavailable(body.get("message", "RAG generation is unavailable"))
    if response.status_code >= 500:
        raise RAGServiceUnavailable("RAG server returned {}".format(response.status_code))
    if response.status_code >= 400:
        raise RAGBadResponse(body.get("error", "RAG request was rejected"))
    return _validate_response(body)


def health():
    if not Config.RAG_ENABLED:
        return {"status": "disabled"}
    try:
        response = requests.get("{}/health".format(Config.RAG_SERVER_URL), timeout=(1, 2))
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}