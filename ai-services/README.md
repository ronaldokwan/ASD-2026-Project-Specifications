# Shared AI services

Team-owned services. Changes here must be agreed by the whole team – they affect
every student's feature.

| Service | Port | Status |
|---|---|---|
| `ai-mode/` | 7000 | **Implemented** |

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
  "model": "qwen2.5:0.5b",
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
