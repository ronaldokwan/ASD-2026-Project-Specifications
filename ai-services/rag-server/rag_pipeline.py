"""Shared RAG pipeline for indexing, retrieval and grounded answers.

Documents are chunked and stored in ChromaDB with deterministic hash
embeddings. Ollama generates answers from retrieved chunks only.
"""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import chromadb
import requests

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", BASE_DIR / "data"))
CORPUS_PATH = DATA_DIR / "corpus.jsonl"
AUDIT_PATH = DATA_DIR / "rag-audit.jsonl"
CHROMA_PATH = DATA_DIR / "chroma"

COLLECTION_NAME = "asd_group40_shared_corpus"
EMBED_VECTOR_SIZE = 256

# Remove common terms before hashing so they do not dominate similarity.
_STOPWORDS = frozenset((
    "a an the is are was were of to and or in on at for it this that how what "
    "does do i my with as be has have very so but not just"
).split())

# ChromaDB's "l2" space returns squared L2 distance over the (unit-norm)
# vectors below: 0.0 = identical, 2.0 = no shared vocabulary at all,
# 4.0 = maximally opposite. A chunk closer than RELEVANT_DISTANCE has real
# keyword overlap with the query and counts as supporting evidence; anything
# else is treated as noise (see tests/test_rag_pipeline.py for calibration).
RELEVANT_DISTANCE = 1.5

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

_collection = None
_knowledge_loaded = False
_knowledge_lock = threading.Lock()


class RAGValidationError(ValueError):
    """The caller supplied an invalid RAG request or document."""


class RAGModelUnavailable(RuntimeError):
    """The local generation model could not produce an answer."""


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def embed_texts(texts):
    """Create deterministic normalized hashing-trick bag-of-words vectors.

    Each token hashes to one signed bucket, then the vector is L2-normalised.
    """
    vectors = []
    for text in texts:
        values = [0.0] * EMBED_VECTOR_SIZE
        tokens = (text or "").lower().split()
        for token in tokens:
            token = token.strip(".,!?;:'\"")
            if not token or token in _STOPWORDS:
                continue
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % EMBED_VECTOR_SIZE
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[index] += sign
        norm = sum(v * v for v in values) ** 0.5
        if norm > 0:
            values = [v / norm for v in values]
        vectors.append(values)
    return vectors


def get_collection():
    global _collection
    if _collection is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "l2"}
        )
    return _collection


def append_audit(action, request_payload, output_summary, status):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "request_id": str(uuid.uuid4()),
        "action": action,
        "request": request_payload,
        "output_summary": output_summary,
        "status": status,
        "timestamp": now_iso(),
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def chunk_text(text, max_words=80):
    words = (text or "").split()
    if not words:
        return []
    return [
        " ".join(words[i:i + max_words])
        for i in range(0, len(words), max_words)
    ]


def _normalise_metadata(metadata):
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise RAGValidationError("document metadata must be an object")
    cleaned = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 80:
            raise RAGValidationError("metadata keys must be non-empty strings up to 80 characters")
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, type(None)):
            raise RAGValidationError(
                "metadata values must be strings, numbers or booleans"
            )
        cleaned[key.strip()] = value
    return cleaned


def _normalise_documents(documents):
    if not isinstance(documents, list) or not documents:
        raise RAGValidationError("documents must be a non-empty list")
    cleaned = []
    for document in documents:
        if not isinstance(document, dict):
            raise RAGValidationError("each document must be an object")
        doc_id = document.get("id")
        text = document.get("text")
        if not isinstance(doc_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", doc_id):
            raise RAGValidationError(
                "document id must use 1-160 letters, numbers, '.', '_', ':' or '-'"
            )
        if not isinstance(text, str) or not text.strip():
            raise RAGValidationError("document text must be a non-empty string")
        if len(text) > 20000:
            raise RAGValidationError("document text must be 20000 characters or fewer")
        cleaned.append({
            "id": doc_id,
            "text": text.strip(),
            "metadata": _normalise_metadata(document.get("metadata")),
        })
    return cleaned


def _normalise_query(query, top_k, filters):
    if not isinstance(query, str) or not query.strip():
        raise RAGValidationError("query must be a non-empty string")
    question = query.strip()
    if not 3 <= len(question) <= 500:
        raise RAGValidationError("query must be between 3 and 500 characters")
    if isinstance(top_k, bool):
        raise RAGValidationError("top_k must be an integer between 1 and 20")
    try:
        top_k = int(top_k)
    except (TypeError, ValueError) as exc:
        raise RAGValidationError("top_k must be an integer between 1 and 20") from exc
    if not 1 <= top_k <= 20:
        raise RAGValidationError("top_k must be an integer between 1 and 20")
    if filters is not None and not isinstance(filters, dict):
        raise RAGValidationError("filters must be an object")
    cleaned_filters = _normalise_metadata(filters) if filters else None
    return question, top_k, cleaned_filters


def _read_corpus():
    if not CORPUS_PATH.exists():
        return []
    chunks = []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def _write_corpus(chunks):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk) + "\n")


def _knowledge_documents(path):
    """Convert one checked-in Markdown policy into section-level documents."""
    source = path.name
    current_section = None
    current_lines = []
    documents = []

    def append_section():
        if current_section and current_lines:
            slug = re.sub(r"[^a-z0-9]+", "-", current_section.lower()).strip("-")
            text = "{}\n{}".format(current_section, " ".join(current_lines).strip())
            documents.append({
                "id": "knowledge:customer_accounts:{}:{}".format(path.stem, slug),
                "text": text,
                "metadata": {
                    "feature": "customer_accounts",
                    "source": source,
                    "section": current_section,
                },
            })

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            append_section()
            current_section = line[3:].strip()
            current_lines = []
        elif current_section and line:
            current_lines.append(line)
    append_section()
    return documents


def load_knowledge_sources(force=False):
    """Idempotently index every checked-in Markdown knowledge source."""
    global _knowledge_loaded
    with _knowledge_lock:
        if _knowledge_loaded and not force:
            return {"ok": True, "knowledge_loaded": True, "documents_indexed": 0}
        documents = []
        if KNOWLEDGE_DIR.exists():
            for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
                documents.extend(_knowledge_documents(path))
        if not documents:
            raise RAGValidationError("no checked-in RAG knowledge documents were found")
        outcome = upsert_documents(documents)
        _knowledge_loaded = True
        return dict(outcome, knowledge_loaded=True)


def upsert_documents(documents):
    """Add or replace one or more documents in the shared corpus.

    ``documents``: list of {"id": str, "text": str, "metadata": dict}.
    A document with an id that already exists is replaced (its old chunks
    are dropped first) so callers can re-index an edited review/FAQ/etc.
    """
    documents = _normalise_documents(documents)
    document_ids = {document["id"] for document in documents}
    corpus = [c for c in _read_corpus() if c["doc_id"] not in document_ids]
    new_chunks = []
    for doc in documents:
        pieces = chunk_text(doc["text"]) or [doc["text"]]
        for index, piece in enumerate(pieces):
            new_chunks.append({
                "chunk_id": "{}::{}".format(doc["id"], index),
                "doc_id": doc["id"],
                "text": piece,
                "metadata": doc.get("metadata") or {},
                "indexed_at": now_iso(),
            })

    corpus.extend(new_chunks)
    _write_corpus(corpus)

    collection = get_collection()
    for doc in documents:
        _delete_from_collection(collection, doc["id"])
    if new_chunks:
        collection.add(
            ids=[c["chunk_id"] for c in new_chunks],
            documents=[c["text"] for c in new_chunks],
            metadatas=[dict(c["metadata"], doc_id=c["doc_id"]) for c in new_chunks],
            embeddings=embed_texts([c["text"] for c in new_chunks]),
        )

    return {"ok": True, "documents_indexed": len(documents), "chunks_indexed": len(new_chunks)}


def _delete_from_collection(collection, doc_id):
    collection.delete(where={"doc_id": doc_id})


def delete_document(doc_id):
    """Remove a document (all its chunks) from the shared corpus."""
    if not isinstance(doc_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", doc_id):
        raise RAGValidationError("invalid document id")
    corpus = _read_corpus()
    remaining = [c for c in corpus if c["doc_id"] != doc_id]
    removed = len(corpus) - len(remaining)
    _write_corpus(remaining)
    _delete_from_collection(get_collection(), doc_id)
    return {"ok": True, "chunks_removed": removed}


def retrieve_context(query, top_k=5, filters=None):
    """Return the top-k chunks for ``query``, optionally filtered by metadata."""
    query, top_k, filters = _normalise_query(query, top_k, filters)
    collection = get_collection()
    if collection.count() == 0:
        return []

    where = dict(filters) if filters else None
    results = collection.query(
        query_embeddings=embed_texts([query]),
        n_results=min(top_k, collection.count()),
        where=where,
    )

    ids = (results.get("ids") or [[]])[0]
    docs = (results.get("documents") or [[]])[0]
    metas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    ranked = []
    for i, chunk_id in enumerate(ids):
        ranked.append({
            "chunk_id": chunk_id,
            "doc_id": (metas[i] or {}).get("doc_id") if i < len(metas) else None,
            "text": docs[i] if i < len(docs) else "",
            "metadata": metas[i] if i < len(metas) else {},
            "distance": distances[i] if i < len(distances) else None,
        })
    return ranked


def confidence_from_results(relevant_count):
    if relevant_count >= 3:
        return "high"
    if relevant_count >= 1:
        return "medium"
    return "low"


def _lexical_terms(text):
    """Return normalized terms for deterministic lexical matching."""
    terms = set()
    for token in re.findall(r"[a-z0-9]+", (text or "").casefold()):
        if token in _STOPWORDS or len(token) < 2:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            token = token[:-1]
        terms.add(token)
    return terms


def _multi_tier_reward_tiers(query):
    """Return explicitly mentioned tiers for a clear multi-tier comparison."""
    query_terms = _lexical_terms(query)
    comparison_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    has_reward_intent = bool(query_terms.intersection({"benefit", "reward"}))
    has_comparison_intent = bool(comparison_terms.intersection({
        "difference", "different", "compare", "comparison", "versus", "vs",
    }))
    if not has_reward_intent and not has_comparison_intent:
        return None

    lowered_query = query.casefold()
    mentioned = [
        tier for tier in ("bronze", "silver", "gold")
        if tier in query_terms
    ]
    if len(mentioned) < 2:
        return None
    return sorted(mentioned, key=lowered_query.find)


def _select_multi_tier_reward_results(results, tiers):
    """Select only the membership evidence for explicitly requested tiers."""
    results_by_section = {
        (result.get("metadata") or {}).get("section", "").casefold(): result
        for result in results
    }
    return [
        results_by_section["{} membership".format(tier)]
        for tier in tiers
        if "{} membership".format(tier) in results_by_section
    ]


def _select_membership_conditions_result(query, results):
    """Select conditions for an explicit tier-selection question, if present."""
    query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    asks_how_tiers_are_set = (
        bool(query_terms.intersection({"tier", "tiers"}))
        and bool(query_terms.intersection({
            "select", "selected", "selection", "calculate", "calculated",
            "automatic", "automatically",
        }))
    )
    if not asks_how_tiers_are_set:
        return None
    return next(
        (
            result for result in results
            if (result.get("metadata") or {}).get("section")
            == "Membership Conditions"
        ),
        None,
    )


def _select_reward_restrictions_result(query, results):
    """Select restrictions when the question asks how a reward may be used."""
    query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    restriction_terms = {
        "cash", "exchange", "exchanged", "apply", "applied", "email",
        "emailed", "save", "saved", "store", "stored", "persist",
        "persisted", "persistence",
    }
    if not query_terms.intersection(restriction_terms):
        return None
    return next(
        (
            result for result in results
            if (result.get("metadata") or {}).get("section")
            == "Reward Restrictions"
        ),
        None,
    )


def _select_relevant_results(query, results):
    """Combine the strict vector cutoff with unambiguous lexical evidence."""
    query_terms = _lexical_terms(query)
    lexical_scores = [
        len(query_terms.intersection(_lexical_terms(result.get("text"))))
        for result in results
    ]
    best_lexical_score = max(lexical_scores, default=0)
    selected = []
    for result, lexical_score in zip(results, lexical_scores):
        vector_relevant = (
            result["distance"] is not None
            and result["distance"] < RELEVANT_DISTANCE
        )
        lexical_relevant = (
            best_lexical_score >= 2
            and lexical_score == best_lexical_score
        )
        if vector_relevant or lexical_relevant:
            selected.append(result)
    return selected


def _generate_with_ollama(query, context_text):
    prompt = (
        "Answer the question using ONLY the source excerpts in the context below. "
        "Copy supporting policy wording exactly instead of paraphrasing it. Preserve "
        "every limiting or modal term (for example: may, must, only, either, next, "
        "one, and not), singular/plural scope, and whether options are alternatives. "
        "Never turn an option into a guarantee or a one-time benefit into a continuing "
        "benefit. Do not begin with a source section heading. Be factual and concise "
        "(1-2 sentences). If the context does not answer the question, reply exactly: "
        "Insufficient evidence.\n\n"
        "QUESTION:\n{}\n\nCONTEXT:\n{}\n".format(query, context_text)
    )
    try:
        response = requests.post(
            "{}/api/generate".format(OLLAMA_URL),
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        answer = body.get("response") if isinstance(body, dict) else None
        return str(answer or "").strip() or "Insufficient evidence."
    except (requests.RequestException, ValueError) as exc:
        raise RAGModelUnavailable("local language model is unavailable") from exc


def _remove_leading_section_heading(answer, results):
    """Remove a retrieved section heading copied verbatim into an answer."""
    cleaned = answer.strip()
    for result in results:
        section = (result.get("metadata") or {}).get("section")
        if not isinstance(section, str) or not section.strip():
            continue
        heading = section.strip()
        match = re.match(
            r"^{}(?:\s*[:\-\u2013\u2014]\s*|\s+)".format(re.escape(heading)),
            cleaned,
            flags=re.IGNORECASE,
        )
        if match and cleaned[match.end():].strip():
            remainder = cleaned[match.end():].strip()
            for index, character in enumerate(remainder):
                if character.isalpha():
                    return remainder[:index] + character.upper() + remainder[index + 1:]
            return remainder
    return cleaned


def _normalise_grounding_text(value):
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _extractive_evidence(result):
    """Return retrieved evidence without its separately displayed section heading."""
    return _remove_leading_section_heading(result.get("text") or "", [result])


def _extractive_supporting_results(answer, results):
    """Map a verbatim answer span to only the evidence sections it uses."""
    normalised_answer = _normalise_grounding_text(answer)
    if not normalised_answer:
        return []

    evidence = [
        _normalise_grounding_text(_extractive_evidence(result))
        for result in results
    ]
    combined_evidence = " ".join(evidence)
    answer_start = combined_evidence.find(normalised_answer)
    if answer_start < 0:
        return []

    answer_end = answer_start + len(normalised_answer)
    supporting_results = []
    evidence_start = 0
    for result, section_evidence in zip(results, evidence):
        evidence_end = evidence_start + len(section_evidence)
        if answer_start < evidence_end and answer_end > evidence_start:
            supporting_results.append(result)
        evidence_start = evidence_end + 1
    return supporting_results


def _is_extractive_answer(answer, results):
    """Accept an answer only when its wording occurs verbatim in retrieved evidence."""
    return bool(_extractive_supporting_results(answer, results))


def _extractive_fallback(results, include_all=False):
    """Return retrieved evidence rather than an unsafe model paraphrase."""
    evidence = [
        _extractive_evidence(result)
        for result in results
        if _extractive_evidence(result)
    ]
    if include_all:
        return " ".join(evidence)
    return evidence[0] if evidence else ""


def answer_question(query, top_k=5, filters=None):
    """Retrieve + generate: the full RAG flow returned to a caller's backend.

    Returns one of two shapes:
      * insufficient context: {"status": "insufficient_context", "confidence":
        "insufficient", "sources": [], "message": "..."}
      * grounded answer: {"status": "ok", "answer": "...", "sources": [...],
        "confidence": "high"|"medium"|"low", "retrieved_count": int}
    """
    start = time.time()
    query, top_k, filters = _normalise_query(query, top_k, filters)
    load_knowledge_sources()
    comparison_tiers = _multi_tier_reward_tiers(query)
    candidate_k = (
        max(top_k, len(comparison_tiers) + 2)
        if comparison_tiers else top_k
    )
    results = retrieve_context(query, top_k=candidate_k, filters=filters)
    if comparison_tiers:
        relevant = _select_multi_tier_reward_results(
            results, comparison_tiers
        )[:top_k]
    else:
        reward_restrictions = _select_reward_restrictions_result(query, results)
        membership_conditions = _select_membership_conditions_result(query, results)
        relevant = (
            [reward_restrictions]
            if reward_restrictions else (
                [membership_conditions]
                if membership_conditions else _select_relevant_results(query, results)
            )
        )

    if not relevant:
        output = {
            "status": "insufficient_context",
            "answer": "",
            "confidence": "insufficient",
            "sources": [],
            "message": "Insufficient relevant context was found.",
        }
        append_audit(
            "answer_question", {"query": query, "filters": filters},
            output, "insufficient",
        )
        return output

    context_text = "\n\n".join(r["text"] for r in relevant)
    try:
        answer = _generate_with_ollama(query, context_text)
    except RAGModelUnavailable:
        output = {
            "status": "service_unavailable",
            "answer": "",
            "confidence": "unavailable",
            "sources": [],
            "message": "The local language model is unavailable.",
        }
        append_audit(
            "answer_question", {"query": query, "filters": filters}, output, "unavailable"
        )
        return output

    if (
        answer.strip().lower().startswith("insufficient evidence")
        and not comparison_tiers
    ):
        output = {
            "status": "insufficient_context",
            "answer": "",
            "confidence": "insufficient",
            "sources": [],
            "message": "Insufficient relevant context was found.",
        }
        append_audit(
            "answer_question", {"query": query, "filters": filters}, output, "insufficient"
        )
        return output
    answer = _remove_leading_section_heading(answer, relevant)
    answer_mode = "generated"
    if not _is_extractive_answer(answer, relevant):
        answer = _extractive_fallback(
            relevant, include_all=bool(comparison_tiers)
        )
        answer_mode = "extractive_fallback"
    relevant = _extractive_supporting_results(answer, relevant)
    confidence = confidence_from_results(len(relevant))

    output = {
        "status": "ok",
        "answer": answer,
        "sources": [
            {
                "doc_id": r["doc_id"],
                "chunk_id": r["chunk_id"],
                "source": r["metadata"].get("source", r["doc_id"]),
                "section": r["metadata"].get("section", "Retrieved context"),
                "snippet": r["text"][:200],
                "metadata": r["metadata"],
            }
            for r in relevant
        ],
        "confidence": confidence,
        "retrieved_count": len(relevant),
        "elapsed_ms": int((time.time() - start) * 1000),
    }
    append_audit(
        "answer_question", {"query": query, "filters": filters},
        {
            "confidence": confidence,
            "retrieved_count": len(relevant),
            "answer_mode": answer_mode,
        },
        "ok",
    )
    return output
