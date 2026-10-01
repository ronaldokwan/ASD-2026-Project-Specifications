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
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", True)
    yield


def seed_reviews():
    rag_pipeline.upsert_documents([
        {"id": "r1", "text": "The battery lasts all day and the noise cancelling is fantastic.",
         "metadata": {"feature": "reviews", "product_sku": "SKU-AUD-1001"}},
        {"id": "r2",
         "text": "Headband pinches after an hour of wear, uncomfortable for long trips.",
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
    results = rag_pipeline.retrieve_context(
        "product", top_k=5, filters={"product_sku": "SKU-HOM-3001"}
    )
    assert all(r["metadata"].get("product_sku") == "SKU-HOM-3001" for r in results)


def test_answer_question_returns_insufficient_context_for_unrelated_query():
    seed_reviews()
    output = rag_pipeline.answer_question("What is the warranty policy for laptops?", top_k=5)
    assert output["status"] == "insufficient_context"
    assert output["confidence"] == "insufficient"
    assert output["sources"] == []


def test_answer_question_returns_grounded_answer_with_citations(monkeypatch):
    seed_reviews()
    monkeypatch.setattr(
        rag_pipeline, "_generate_with_ollama",
        lambda q, c: "The battery lasts all day and the noise cancelling is fantastic.",
    )

    output = rag_pipeline.answer_question(
        "How is the battery life?", top_k=5,
        filters={"product_sku": "SKU-AUD-1001"},
    )

    assert output["status"] == "ok"
    assert output["answer"] == (
        "The battery lasts all day and the noise cancelling is fantastic."
    )
    assert output["confidence"] in ("high", "medium", "low")
    assert output["sources"]
    assert output["sources"][0]["doc_id"] in ("r1", "r2")


def test_delete_document_removes_it_from_retrieval(monkeypatch):
    seed_reviews()
    monkeypatch.setattr(rag_pipeline, "_generate_with_ollama", lambda q, c: "answer")

    rag_pipeline.delete_document("r1")
    output = rag_pipeline.answer_question(
        "How is the battery life?", top_k=5,
        filters={"product_sku": "SKU-AUD-1001"},
    )

    doc_ids = [s["doc_id"] for s in output.get("sources", [])]
    assert "r1" not in doc_ids


def test_upsert_replaces_existing_document():
    rag_pipeline.upsert_documents([{"id": "r1", "text": "Original text here.", "metadata": {}}])
    rag_pipeline.upsert_documents([{
        "id": "r1", "text": "Updated review text about battery.", "metadata": {}
    }])

    results = rag_pipeline.retrieve_context("battery", top_k=5)
    matching = [r for r in results if r["doc_id"] == "r1"]
    assert matching
    assert "Updated" in matching[0]["text"]


def test_checked_in_customer_policy_is_loaded_with_source_metadata(monkeypatch):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    outcome = rag_pipeline.load_knowledge_sources()
    assert outcome["documents_indexed"] == 5

    results = rag_pipeline.retrieve_context(
        "Gold loyalty benefits",
        filters={"feature": "customer_accounts"},
    )
    assert results
    gold = next(
        result for result in results
        if result["metadata"]["section"] == "Gold Membership"
    )
    assert gold["metadata"]["source"] == "customer-loyalty-policy.md"


@pytest.mark.parametrize("query, expected_section, expected_text", [
    (
        "What benefits are available to Bronze customers?",
        "Bronze Membership",
        "Bronze customers may receive either free standard delivery",
    ),
    (
        "What reward can a Silver member receive?",
        "Silver Membership",
        "Silver customers may receive either ten percent off",
    ),
    (
        "Which benefits does the GOLD tier offer?",
        "Gold Membership",
        "Gold customers may receive either fifteen percent off",
    ),
    (
        "Can Gold rewards be exchanged for cash?",
        "Reward Restrictions",
        "Loyalty rewards cannot be exchanged for cash.",
    ),
    (
        "How are loyalty tiers selected?",
        "Membership Conditions",
        "The administrator manually selects Bronze, Silver, or Gold.",
    ),
])
def test_supported_policy_questions_select_the_expected_section(
    monkeypatch, query, expected_section, expected_text
):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    generation_calls = []

    def quote_evidence(_query, context):
        generation_calls.append(context)
        return context

    monkeypatch.setattr(rag_pipeline, "_generate_with_ollama", quote_evidence)
    output = rag_pipeline.answer_question(
        query,
        filters={"feature": "customer_accounts"},
    )

    assert generation_calls
    assert output["status"] == "ok"
    assert [source["section"] for source in output["sources"]] == [expected_section]
    assert output["sources"][0]["source"] == "customer-loyalty-policy.md"
    assert expected_text in output["answer"]
    assert expected_text in output["sources"][0]["snippet"]


@pytest.mark.parametrize("query, expected_sections", [
    (
        "difference between gold and silver",
        ["Gold Membership", "Silver Membership"],
    ),
    (
        "difference between gold and silver tier",
        ["Gold Membership", "Silver Membership"],
    ),
    (
        "difference between gold, silver and bronze",
        ["Gold Membership", "Silver Membership", "Bronze Membership"],
    ),
    (
        "Compare Bronze and Gold.",
        ["Bronze Membership", "Gold Membership"],
    ),
    (
        "Compare Bronze, Silver and Gold.",
        ["Bronze Membership", "Silver Membership", "Gold Membership"],
    ),
    (
        "Gold vs Silver",
        ["Gold Membership", "Silver Membership"],
    ),
    (
        "Any difference between gold, silver and bronze in terms of rewards?",
        ["Gold Membership", "Silver Membership", "Bronze Membership"],
    ),
    (
        "Compare Bronze and Gold rewards.",
        ["Bronze Membership", "Gold Membership"],
    ),
])
def test_multi_tier_reward_comparison_uses_every_named_membership_section(
    monkeypatch, query, expected_sections
):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    monkeypatch.setattr(
        rag_pipeline,
        "_generate_with_ollama",
        lambda _query, _context: "An unsupported paraphrase.",
    )

    output = rag_pipeline.answer_question(
        query,
        filters={"feature": "customer_accounts"},
    )

    assert output["status"] == "ok"
    assert [source["section"] for source in output["sources"]] == expected_sections
    assert all(
        source["source"] == "customer-loyalty-policy.md"
        for source in output["sources"]
    )
    assert "Membership Conditions" not in {
        source["section"] for source in output["sources"]
    }
    for section in expected_sections:
        tier = section.removesuffix(" Membership")
        assert "{} customers may receive either".format(tier) in output["answer"]


def test_generated_answer_does_not_repeat_retrieved_section_heading(monkeypatch):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    monkeypatch.setattr(
        rag_pipeline,
        "_generate_with_ollama",
        lambda _query, _context: (
            "Gold Membership Gold customers may receive either fifteen percent off "
            "the next purchase or early access to the next seasonal sale."
        ),
    )

    output = rag_pipeline.answer_question(
        "What benefits are available to Gold customers?",
        filters={"feature": "customer_accounts"},
    )

    assert output["answer"].startswith("Gold customers may receive")
    assert not output["answer"].startswith("Gold Membership")
    assert output["sources"][0]["source"] == "customer-loyalty-policy.md"
    assert output["sources"][0]["section"] == "Gold Membership"
    assert len(output["sources"]) == 1
    assert output["sources"][0]["snippet"].startswith(
        "Gold Membership Gold customers may receive"
    )
    assert rag_pipeline._remove_leading_section_heading(
        "Gold Membership benefits are policy-limited.",
        [{"metadata": {"section": "Gold Membership"}}],
    ) == "Benefits are policy-limited."


@pytest.mark.parametrize("query, altered_answer", [
    (
        "What benefits are available to Gold customers?",
        "Gold customers receive both fifteen percent off purchases and early access "
        "to seasonal sales.",
    ),
    (
        "What are the benefits for gold member?",
        "Gold Membership benefits include receiving a fifteen percent discount on "
        "subsequent purchases and early access to seasonal sales.",
    ),
    (
        "What reward does a Gold customer receive?",
        "Gold customers receive fifteen percent off future purchases or early access "
        "to seasonal sales.",
    ),
])
def test_policy_semantic_drift_uses_exact_retrieved_evidence(
    monkeypatch, query, altered_answer
):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    monkeypatch.setattr(
        rag_pipeline,
        "_generate_with_ollama",
        lambda _query, _context: altered_answer,
    )

    output = rag_pipeline.answer_question(
        query,
        filters={"feature": "customer_accounts"},
    )

    assert output["answer"] == (
        "Gold customers may receive either fifteen percent off the next purchase or "
        "early access to the next seasonal sale. These are the only approved Gold "
        "loyalty benefits."
    )
    assert "either" in output["answer"]
    assert "next purchase" in output["answer"]
    assert not any(
        wording in output["answer"].lower()
        for wording in ("both", "subsequent purchases", "future purchases")
    )
    assert output["sources"][0]["section"] == "Gold Membership"
    assert output["sources"][0]["snippet"].startswith(
        "Gold Membership Gold customers may receive either"
    )


def test_customer_policy_returns_insufficient_context_for_unsupported_question(
    monkeypatch,
):
    monkeypatch.setattr(rag_pipeline, "_knowledge_loaded", False)
    monkeypatch.setattr(
        rag_pipeline,
        "_generate_with_ollama",
        lambda _query, _context: pytest.fail("unsupported query reached generation"),
    )
    output = rag_pipeline.answer_question(
        "How do I reset an administrator password?",
        filters={"feature": "customer_accounts"},
    )
    assert output["status"] == "insufficient_context"
    assert output["answer"] == ""
    assert output["sources"] == []


def test_ollama_unavailable_is_not_reported_as_grounded(monkeypatch):
    seed_reviews()

    def unavailable(_query, _context):
        raise rag_pipeline.RAGModelUnavailable("offline")

    monkeypatch.setattr(rag_pipeline, "_generate_with_ollama", unavailable)
    output = rag_pipeline.answer_question(
        "How is the battery life?",
        filters={"feature": "reviews"},
    )
    assert output == {
        "status": "service_unavailable",
        "answer": "",
        "confidence": "unavailable",
        "sources": [],
        "message": "The local language model is unavailable.",
    }


def test_model_insufficient_evidence_is_an_insufficient_context_result(monkeypatch):
    seed_reviews()
    monkeypatch.setattr(
        rag_pipeline, "_generate_with_ollama", lambda _query, _context: "Insufficient evidence."
    )
    output = rag_pipeline.answer_question(
        "How is the battery life?",
        filters={"feature": "reviews"},
    )
    assert output["status"] == "insufficient_context"
    assert output["answer"] == ""
    assert output["sources"] == []


@pytest.mark.parametrize("query, top_k, filters", [
    ("ok", 0, None),
    ("valid question", "many", None),
    ("valid question", 5, ["not", "an", "object"]),
])
def test_query_validation_rejects_invalid_controls(query, top_k, filters):
    with pytest.raises(rag_pipeline.RAGValidationError):
        rag_pipeline.retrieve_context(query, top_k=top_k, filters=filters)
