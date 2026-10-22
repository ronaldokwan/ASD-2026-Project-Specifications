"""Client for the shared RAG server - grounded answers about the catalogue.

frontend -> backend/API -> shared RAG server (/rag/query) -> Ollama -> LLM

"""

import logging

import requests

from .config import Config

log = logging.getLogger(__name__)

_CONFIDENCE = ("high", "medium", "low")
# Indexing rides along with a catalogue write, so it must fail fast; only a
# query waits for the LLM. (connect, read) seconds.
_SYNC_TIMEOUT = (3, 15)
_synced = False


class RAGServiceUnavailable(RuntimeError):
    """The RAG server or its local model is disabled or unavailable."""


class RAGBadResponse(RuntimeError):
    """The RAG server returned a malformed response."""


# ------------------------------------------------------------ corpus content
def document_id(product_id):
    return "catalogue:product:{}".format(product_id)


def product_document(product):
    """One catalogue row as a short, citable RAG document."""
    status = product["status"]
    text = "{name} ({sku}) is {article} {status} {category} product priced at {price:.2f} AUD."
    text = text.format(
        name=product["name"],
        sku=product["sku"],
        article="an" if status[:1] in "aeiou" else "a",
        status=status,
        category=product["category"],
        price=float(product["price"]),
    )
    description = (product.get("description") or "").strip()
    if description:
        text = "{} {}".format(text, description)
    return {
        "id": document_id(product["id"]),
        "text": text,
        "metadata": {
            "feature": Config.RAG_FEATURE,
            "source": "Product Catalogue database",
            "section": "{} {}".format(product["sku"], product["name"]),
            "product_sku": product["sku"],
            "category": product["category"],
            "status": status,
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
        raise RAGServiceUnavailable(
            "RAG server is unreachable at {}".format(url)
        ) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise RAGBadResponse("RAG server returned non-JSON data") from exc
    return response, body


def sync_products(products):
    """Index every catalogue product into the shared corpus (re-index)."""
    global _synced
    if not Config.RAG_ENABLED:
        raise RAGServiceUnavailable("RAG integration is disabled")
    if not products:
        return {"ok": True, "documents_indexed": 0, "chunks_indexed": 0}
    response, body = _post(
        "/rag/documents",
        {"documents": [product_document(p) for p in products]},
        timeout=_SYNC_TIMEOUT,
    )
    if response.status_code >= 400 or not body.get("ok"):
        raise RAGBadResponse(body.get("error", "RAG re-index was rejected"))
    _synced = True
    return body


def sync_product(product):
    """Best-effort: a RAG outage must never break the catalogue write itself."""
    if not Config.RAG_ENABLED:
        return
    try:
        _post(
            "/rag/documents",
            {"documents": [product_document(product)]},
            timeout=_SYNC_TIMEOUT,
        )
    except (RAGServiceUnavailable, RAGBadResponse) as exc:
        log.warning("RAG sync skipped for product %s: %s", product.get("id"), exc)


def remove_product(product_id):
    if not Config.RAG_ENABLED:
        return
    url = "{}/rag/documents/{}".format(Config.RAG_SERVER_URL, document_id(product_id))
    try:
        requests.delete(url, timeout=_SYNC_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("RAG removal skipped for product %s: %s", product_id, exc)


def ensure_synced(list_products):
    """Index the catalogue once per process, before its first question."""
    if _synced:
        return
    try:
        sync_products(list_products())
    except Exception as exc:  # noqa: BLE001 - the query below reports the outage
        log.warning("initial RAG catalogue sync failed: %s", exc)


# ---------------------------------------------------------------- validation
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
        if (source.get("metadata") or {}).get("feature") != Config.RAG_FEATURE:
            raise RAGBadResponse("RAG cited a source outside the Product Catalogue")
        cleaned.append(
            {
                "source": source["source"],
                "section": source["section"],
                "snippet": source["snippet"],
                # Full retrieved chunk: what agentic-loop validation checks against.
                "text": (
                    source["text"]
                    if isinstance(source.get("text"), str)
                    else source["snippet"]
                ),
            }
        )
    return cleaned


def _validate_response(body):
    if not isinstance(body, dict):
        raise RAGBadResponse("RAG response must be an object")
    status = body.get("status")
    if status == "insufficient_context":
        if body.get("answer", "") != "" or body.get("sources") != []:
            raise RAGBadResponse(
                "insufficient-context response contains an answer or sources"
            )
        if body.get("confidence") != "insufficient":
            raise RAGBadResponse("insufficient-context response is malformed")
        return {
            "status": status,
            "answer": "",
            "sources": [],
            "confidence": "insufficient",
            "message": body.get("message")
            or "Insufficient relevant context was found.",
        }
    if status != "ok":
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


# ---------------------------------------------------------------------- query
def ask(question):
    """Ask one catalogue question; returns a validated grounded answer."""
    if not Config.RAG_ENABLED:
        raise RAGServiceUnavailable("RAG integration is disabled")
    response, body = _post(
        "/rag/query",
        {
            "query": question,
            "top_k": Config.RAG_TOP_K,
            "filters": {"feature": Config.RAG_FEATURE},
        },
    )
    if response.status_code == 503 or body.get("status") == "service_unavailable":
        raise RAGServiceUnavailable(
            body.get("message", "RAG generation is unavailable")
        )
    if response.status_code >= 500:
        raise RAGServiceUnavailable(
            "RAG server returned {}".format(response.status_code)
        )
    if response.status_code >= 400:
        raise RAGBadResponse(body.get("error", "RAG request was rejected"))
    return _validate_response(body)


def health():
    if not Config.RAG_ENABLED:
        return {"status": "disabled"}
    try:
        response = requests.get(
            "{}/health".format(Config.RAG_SERVER_URL), timeout=(1, 2)
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
