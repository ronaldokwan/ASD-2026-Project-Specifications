# RAG Tool Contracts

`rag_pipeline.py` implements the pipeline once (corpus -> chunk -> hashing
embedding -> ChromaDB -> retrieve -> Ollama -> cited answer) and is exposed
two ways, exactly like `ai-services/mcp-server/`:

* `server.py` - a real MCP server (stdio, via the official `mcp==2.2.0`
  SDK's `MCPServer`). Launch with `mcp-config.json` from any MCP-aware client.
* `http_server.py` - a plain Flask HTTP front door on port **7003**. This is
  the "shared non-containerised local RAG server" every student backend
  actually calls over the network.

## upsert_documents

- **Purpose:** add or replace one or more documents in the shared corpus.
- **Input:** `documents`: list of `{"id": str, "text": str, "metadata": dict}`.
  A document with an existing id is replaced (old chunks dropped first), so a
  feature can re-index an edited record.
- **Output:** `{"ok": true, "documents_indexed": int, "chunks_indexed": int}`
- **Policy class:** write (index update). Any feature can call this to
  contribute its own domain text (reviews, FAQs, policies, product notes).
- **HTTP:** `POST /rag/documents`

## delete_document

- **Purpose:** remove a document (all its chunks) from the shared corpus.
- **Input:** `doc_id` (path segment on the HTTP route).
- **Output:** `{"ok": true, "chunks_removed": int}`
- **HTTP:** `DELETE /rag/documents/<doc_id>`

## retrieve_context

- **Purpose:** return the top-k chunks for a query, optionally filtered by
  metadata (e.g. `{"product_sku": "SKU-AUD-1001"}`).
- **Input:** `query` (required), `top_k` (default 5), `filters` (optional
  metadata equality filter).
- **Output:** list of `{chunk_id, doc_id, text, metadata, distance}`.
- **Policy class:** read.

## answer_question

- **Purpose:** the full grounded-answer flow: retrieve, then generate with
  the local LLM using only the retrieved chunks.
- **Input:** `query` (required), `top_k` (default 5), `filters` (optional).
- **Output (two shapes):**
  - No chunk close enough to the query (`distance >= 1.5`):
    `{"status": "insufficient_context", "confidence": "insufficient",
    "sources": [], "message": "..."}` - the frontend must render this as its
    own state, not as a normal low-confidence answer.
  - Otherwise: `{"status": "ok", "answer": str, "sources": [{"doc_id",
    "chunk_id", "snippet", "metadata"}], "confidence": "high"|"medium"|"low",
    "retrieved_count": int}`. Confidence is driven by how many chunks were
    close enough to count as supporting evidence (3+ = high, 1-2 = medium),
    never by the LLM's own self-reported certainty.
- **HTTP:** `POST /rag/query`
- **Auditing:** every call is appended to `data/rag-audit.jsonl`.

If Ollama is unavailable, the server returns HTTP 503 with
`status: "service_unavailable"`, an empty answer and sources, and
`confidence: "unavailable"`. That state is distinct from insufficient
context and is never presented as a grounded answer.

## Checked-in knowledge

Markdown sources in `knowledge/` are indexed deterministically on the first
query. `customer-loyalty-policy.md` is split by its level-two section headings
and indexed with `feature: customer_accounts`, source filename and section
metadata. Runtime JSONL, audit and Chroma data remain under ignored `data/`.

## Adding your own content

Any feature can push its own text into the shared corpus:

```
POST http://localhost:7003/rag/documents
{"documents": [{"id": "review-r1", "text": "...", "metadata": {"feature": "reviews", "product_sku": "SKU-AUD-1001"}}]}
```

Use a `metadata.feature` tag so `filters` can scope a query to your own
content, and keep the corpus in sync on create/update/delete of the source
record (best-effort - a RAG-server blip should never break the primary
write), the same pattern Student 5's `backend/app/routes.py` uses.
