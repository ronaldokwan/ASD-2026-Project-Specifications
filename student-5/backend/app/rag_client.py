"""HTTP client for the shared RAG server (ai-services/rag-server).

Reviews and Ratings contributes each review's text to the shared corpus (so
"Ask about the reviews" has something to retrieve) and keeps it in sync as
reviews are created, edited or deleted - the same best-effort, never-break-
the-primary-write pattern ``catalogue_client.py`` uses for product name
lookups.
"""

import requests

from .config import Config


class RAGServiceError(RuntimeError):
    """The shared RAG server could not be reached."""


def _document_id(review_id):
    return "review-{}".format(review_id)


def index_review(review):
    """Best-effort: push one review's text into the shared corpus.

    Never raises - a RAG-server blip must not stop a review being saved.
    """
    try:
        requests.post(
            "{}/rag/documents".format(Config.RAG_SERVER_URL),
            json={"documents": [{
                "id": _document_id(review["review_id"]),
                "text": review["review"],
                "metadata": {
                    "feature": "reviews",
                    "product_sku": review["product_sku"],
                    "rating": review["rating"],
                },
            }]},
            timeout=Config.RAG_TIMEOUT,
        )
    except requests.RequestException:
        pass


def remove_review(review_id):
    """Best-effort: drop one review's text from the shared corpus."""
    try:
        requests.delete(
            "{}/rag/documents/{}".format(Config.RAG_SERVER_URL, _document_id(review_id)),
            timeout=Config.RAG_TIMEOUT,
        )
    except requests.RequestException:
        pass


def ask(product_sku, question, top_k=5):
    """Ask a grounded question about one product's reviews.

    Raises RAGServiceError only when the server itself is unreachable -
    "no relevant reviews found" is a normal ``status: insufficient_context``
    response, not an error, and is returned as-is for the caller to render.
    """
    url = "{}/rag/query".format(Config.RAG_SERVER_URL)
    payload = {"query": question, "top_k": top_k, "filters": {"product_sku": product_sku}}
    try:
        response = requests.post(url, json=payload, timeout=Config.RAG_TIMEOUT)
    except requests.RequestException as exc:
        raise RAGServiceError("RAG server unreachable at {}: {}".format(url, exc)) from exc

    if response.status_code >= 400:
        raise RAGServiceError("RAG server returned {}: {}".format(response.status_code, response.text))

    try:
        return response.json()
    except ValueError as exc:
        raise RAGServiceError("RAG server returned a non-JSON response") from exc
