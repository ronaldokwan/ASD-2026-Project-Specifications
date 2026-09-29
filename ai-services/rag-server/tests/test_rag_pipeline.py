"""Unit tests for the shared RAG pipeline.

Embeddings are the pipeline's own deterministic hashing function (no model
needed) and the LLM call is stubbed, so this suite runs fully offline.

Run from the repository root:  pytest ai-services/rag-server/tests -v
"""

import os
import sys
import tempfile

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

# rag_pipeline resolves its data directory from this env var at import time,
# so point it at a scratch directory before importing (same pattern as
# student-5/tests/conftest.py setting DB_PATH before importing the db module).
os.environ["RAG_DATA_DIR"] = tempfile.mkdtemp(prefix="asd-rag-tests-")

import pytest  # noqa: E402

import rag_pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_corpus(monkeypatch, tmp_path):
    """Isolate each test's corpus/index in its own temp directory."""
    monkeypatch.setattr(rag_pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rag_pipeline, "CORPUS_PATH", tmp_path / "corpus.jsonl")
    monkeypatch.setattr(rag_pipeline, "AUDIT_PATH", tmp_path / "rag-audit.jsonl")
    monkeypatch.setattr(rag_pipeline, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(rag_pipeline, "_collection", None)
    yield


def seed_reviews():
    rag_pipeline.upsert_documents([
        {"id": "r1", "text": "The battery lasts all day and the noise cancelling is fantastic.",
         "metadata": {"feature": "reviews", "product_sku": "SKU-AUD-1001"}},
        {"id": "r2", "text": "Headband pinches after an hour of wear, uncomfortable for long trips.",
         "metadata": {"feature": "reviews", "product_sku": "SKU-AUD-1001"}},
        {"id": "r3", "text": "Makes a great cup of coffee every morning, easy to clean.",
         "metadata": {"feature": "reviews", "product_sku": "SKU-HOM-3001"}},
    ])


def test_upsert_and_retrieve_context():
    seed_reviews()
    results = rag_pipeline.retrieve_context("battery life", top_k=5)
    assert results
    assert any("battery" in r["text"].lower() for r in results)


def test_retrieve_context_respects_metadata_filters():
    seed_reviews()
    results = rag_pipeline.retrieve_context("product", top_k=5, filters={"product_sku": "SKU-HOM-3001"})
    assert all(r["metadata"].get("product_sku") == "SKU-HOM-3001" for r in results)


def test_answer_question_returns_insufficient_context_for_unrelated_query():
    seed_reviews()
    output = rag_pipeline.answer_question("What is the warranty policy for laptops?", top_k=5)
    assert output["status"] == "insufficient_context"
    assert output["confidence"] == "insufficient"
    assert output["sources"] == []


def test_answer_question_returns_grounded_answer_with_citations(monkeypatch):
    seed_reviews()
    monkeypatch.setattr(rag_pipeline, "_generate_with_ollama", lambda q, c: "The battery life is excellent.")

    output = rag_pipeline.answer_question("How is the battery life?", top_k=5,
                                           filters={"product_sku": "SKU-AUD-1001"})

    assert output["status"] == "ok"
    assert output["answer"] == "The battery life is excellent."
    assert output["confidence"] in ("high", "medium", "low")
    assert output["sources"]
    assert output["sources"][0]["doc_id"] in ("r1", "r2")


def test_delete_document_removes_it_from_retrieval(monkeypatch):
    seed_reviews()
    monkeypatch.setattr(rag_pipeline, "_generate_with_ollama", lambda q, c: "answer")

    rag_pipeline.delete_document("r1")
    output = rag_pipeline.answer_question("How is the battery life?", top_k=5,
                                           filters={"product_sku": "SKU-AUD-1001"})

    doc_ids = [s["doc_id"] for s in output.get("sources", [])]
    assert "r1" not in doc_ids


def test_upsert_replaces_existing_document():
    rag_pipeline.upsert_documents([{"id": "r1", "text": "Original text here.", "metadata": {}}])
    rag_pipeline.upsert_documents([{"id": "r1", "text": "Updated review text about battery.", "metadata": {}}])

    results = rag_pipeline.retrieve_context("battery", top_k=5)
    matching = [r for r in results if r["doc_id"] == "r1"]
    assert matching
    assert "Updated" in matching[0]["text"]
