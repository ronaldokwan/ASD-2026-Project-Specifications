# Shared AI services

Team-owned services. Changes here must be agreed by the whole team – they affect
every student's feature.

| Service | Port | Status |
|---|---|---|
| `ai-mode/` | 7001 | **Implemented** |
| `mcp-server/` | 7002 | **Implemented** |
| `rag-server/` | 7003 | **Implemented** |
| `multi-agent/` | 7004 | **Implemented** |

## ai-mode

Implements the shared **Plan → Act → Observe → Adapt** loop (Specification §4.3) and is the only
component that talks to Ollama. Student backends call it instead of calling the LLM directly.

```
POST /agent/run
{
  "goal": "product_copy",
  "task": "Write a product description and suggest a price.",
  "context":  { "category": "Audio", "category_avg_price": 149.5 },
  "output_schema": {
    "description": { "type": "string", "min_words": 25, "max_words": 60 },
    "price":       { "type": "number", "min": 1, "max": 9999 }
  },
  "fallback": { "description": "…", "price": 149.5 }
}
```

Response:

```json
{
  "ok": true,
  "result": { "description": "…", "price": 129.95 },
  "attempts": 1,
  "fallback_used": false,
  "model": "qwen2.5:3b",
  "elapsed_ms": 1840,
  "trace": [ { "step": "Plan", "detail": "…" }, { "step": "Act", "…": "…" } ]
}
```

* `context` is how a backend **grounds** the model in real database facts.
* `output_schema` drives the Observe guardrails.
* `fallback` guarantees the calling UI always gets a usable answer.
* `trace` is the demo/report evidence of the agentic workflow.

Other endpoints: `GET /health` (Ollama + model readiness), `GET /config` (loop configuration).

Tests: `pytest ai-services/ai-mode/tests -v` (LLM is stubbed, so CI runs offline).

## multi-agent (Release 2)

Implements the shared **Planner → Worker → Reviewer → Human Review** workflow (Release 2).
Student backends call it the same way they call AI-Mode:

    frontend -> backend/API -> Multi-Agent Server -> Planner -> Worker -> Reviewer -> Human Review

```
POST /workflow/run
{
  "goal": "restock_plan",
  "task": "Decide whether this product should be restocked given its current stock level.",
  "context":  { "stock_level": 2, "reorder_threshold": 10, "product_name": "Wireless Headphones" },
  "output_schema": { "summary": { "type": "string", "min_words": 5, "max_words": 40 } },
  "fallback": { "summary": "Fallback: stock is low, flag for manual restock review." }
}
```

Response (`status` is always `pending_human_review` - the Reviewer only recommends):

```json
{
  "workflow_id": "8dfdd68c2234",
  "status": "pending_human_review",
  "plan":   { "steps": ["Check the current stock level...", "..."] },
  "worker": { "result": { "summary": "..." } },
  "review": { "verdict": "approve", "recommendation": "...", "risks": [] },
  "trace":  [ { "step": "Planner", "..." }, { "step": "Worker", "..." }, { "step": "Reviewer", "..." } ]
}
```

A human then calls the final decision - approve, correct (optionally supplying `corrected_result`),
partially accept, or reject:

```
POST /workflow/<id>/human-review
{ "decision": "approve" | "correct" | "partial_accept" | "reject", "comment": "...", "reviewer": "..." }
```

Other endpoints: `GET /health`, `GET /config`, `GET /workflow` (recent history / audit trail),
`GET /workflow/<id>` (one record). Every workflow run and human decision is also appended to
`ai-services/multi-agent/data/workflow_log.jsonl` as a durable audit log for the technical report.

Tests: `pytest ai-services/multi-agent/tests -v` (LLM is stubbed, so CI runs offline).
