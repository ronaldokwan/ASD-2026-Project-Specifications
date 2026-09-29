"""Core RAG pipeline: corpus -> chunks -> vectors -> ChromaDB -> retrieve -> answer.

Shared by every student feature. A feature's backend pushes its own domain
text into the corpus (``upsert_documents`` / ``delete_document`` - e.g.
Student 5 pushing review text as reviews are created/edited/deleted) and
queries it (``answer_question``) - the same "shared, used by all student
features" role the shared MCP server plays for tool calls.

Embeddings are a deterministic hashing-based bag-of-words vector rather than
a real semantic embedding model: it needs no extra Ollama model pull, is
fully offline/reproducible, and is good enough for the short, keyword-heavy
text (product reviews, FAQs) this corpus holds. ChromaDB stores and searches
the vectors; Ollama (the same approved local LLM used by AI-Mode) generates
the final grounded answer from the retrieved chunks.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import chromadb
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", BASE_DIR / "data"))
CORPUS_PATH = DATA_DIR / "corpus.jsonl"
AUDIT_PATH = DATA_DIR / "rag-audit.jsonl"
CHROMA_PATH = DATA_DIR / "chroma"

COLLECTION_NAME = "asd_group40_shared_corpus"
EMBED_VECTOR_SIZE = 256

# Common words carry no retrieval signal and would otherwise dominate the
# hashed vector purely by chance collisions - strip them before hashing.
_STOPWORDS = frozenset((
    "a an the is are was were of to and or in on at for it this that how what "
    "does do i my with as be has have very so but not just"
).split())

# ChromaDB's "l2" space returns squared L2 distance over the (unit-norm)
# vectors below: 0.0 = identical, 2.0 = no shared vocabulary at all,
# 4.0 = maximally opposite. A chunk closer than RELEVANT_DISTANCE has real
# keyword overlap with the query and counts as supporting evidence; anything
# else is treated as noise (see tests/test_rag_pipeline.py for calibration).
RELEVANT_DISTANCE = 1.8

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:0.5b")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

_collection = None


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def embed_texts(texts):
    """Deterministic hashing-trick bag-of-words embedding (no model needed).

    Standard feature-hashing vectoriser (as used by e.g. scikit-learn's
    HashingVectorizer): each token is hashed to one of EMBED_VECTOR_SIZE
    buckets with a random sign, then the vector is L2-normalised. This keeps
    cosine similarity close to real keyword overlap - unlike spreading every
    hash byte across every dimension, which drowns genuine overlap in noise
    once more than a couple of documents are indexed.
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


def upsert_documents(documents):
    """Add or replace one or more documents in the shared corpus.

    ``documents``: list of {"id": str, "text": str, "metadata": dict}.
    A document with an id that already exists is replaced (its old chunks
    are dropped first) so callers can re-index an edited review/FAQ/etc.
    """
    corpus = [c for c in _read_corpus() if c["doc_id"] not in {d["id"] for d in documents}]
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
    try:
        collection.delete(where={"doc_id": doc_id})
    except Exception:
        pass


def delete_document(doc_id):
    """Remove a document (all its chunks) from the shared corpus."""
    corpus = _read_corpus()
    remaining = [c for c in corpus if c["doc_id"] != doc_id]
    removed = len(corpus) - len(remaining)
    _write_corpus(remaining)
    _delete_from_collection(get_collection(), doc_id)
    return {"ok": True, "chunks_removed": removed}


def retrieve_context(query, top_k=5, filters=None):
    """Return the top-k chunks for ``query``, optionally filtered by metadata."""
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


def _generate_with_ollama(query, context_text):
    prompt = (
        "Answer the question using ONLY the review excerpts in the context below. "
        "Be factual and concise (1-2 sentences). If the context does not answer the "
        "question, reply exactly: Insufficient evidence.\n\n"
        "QUESTION:\n{}\n\nCONTEXT:\n{}\n".format(query, context_text)
    )
    try:
        response = requests.post(
            "{}/api/generate".format(OLLAMA_URL),
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        return (response.json().get("response") or "").strip() or "Insufficient evidence."
    except requests.RequestException as exc:
        return "Insufficient evidence. (LLM unreachable: {})".format(exc)


def answer_question(query, top_k=5, filters=None):
    """Retrieve + generate: the full RAG flow returned to a caller's backend.

    Returns one of two shapes:
      * insufficient context: {"status": "insufficient_context", "confidence":
        "insufficient", "sources": [], "message": "..."}
      * grounded answer: {"status": "ok", "answer": "...", "sources": [...],
        "confidence": "high"|"medium"|"low", "retrieved_count": int}
    """
    start = time.time()
    results = retrieve_context(query, top_k=top_k, filters=filters)
    relevant = [r for r in results if r["distance"] is not None and r["distance"] < RELEVANT_DISTANCE]

    if not relevant:
        output = {
            "status": "insufficient_context",
            "confidence": "insufficient",
            "sources": [],
            "message": "Not enough relevant context was found to answer this question.",
        }
        append_audit("answer_question", {"query": query, "filters": filters}, output, "insufficient")
        return output

    context_text = "\n\n".join(r["text"] for r in relevant)
    answer = _generate_with_ollama(query, context_text)
    confidence = confidence_from_results(len(relevant))

    output = {
        "status": "ok",
        "answer": answer,
        "sources": [
            {"doc_id": r["doc_id"], "chunk_id": r["chunk_id"], "snippet": r["text"][:200],
             "metadata": r["metadata"]}
            for r in relevant
        ],
        "confidence": confidence,
        "retrieved_count": len(relevant),
        "elapsed_ms": int((time.time() - start) * 1000),
    }
    append_audit(
        "answer_question", {"query": query, "filters": filters},
        {"confidence": confidence, "retrieved_count": len(relevant)}, "ok",
    )
    return output
