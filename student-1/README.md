# Student 1 — Ronaldo Kwan — Product Catalogue

Status: **Implemented.**

Provides the store's product catalogue: browse and filter products by category, full CRUD, and an
AI assistant that drafts a product description and suggests a price grounded in what comparable
products in the same category already cost.

**Release 1** adds, through the frontend UI and this backend/API:

* an **MCP listing check** – the shared MCP server's `check_product_listing` tool reports whether
  a listing is ready to publish and where its price sits against comparable products;
* **Ask the catalogue** – grounded answers from the shared RAG server, citing the catalogue
  policy and the live product records, with a confidence category or an explicit
  insufficient-context result.

## Microservices

| Microservice | Folder | Port | Stack |
|---|---|---|---|
| Frontend | `frontend/` | 3001 | Flask + HTMX + shared CSS theme |
| Backend / API | `backend/` | 8001 | Flask REST API |
| Database | `database/` | 9001 | SQLite behind a small Flask data API |

```
       Docker Compose (containerised)                          ┊  host (native, not containerised)
                                                               ┊
browser ─HTMX─▶ frontend:3001 ─REST─▶ backend:8001 ─REST─▶ database:9001 (SQLite)
                                          │                    ┊
                                          ├─ REST ─────────────┼─▶ AI-Mode :7001   /agent/run, /agent/validate
                                          ├─ MCP Streamable HTTP ▶ MCP server :7002/mcp  check_product_listing
                                          └─ REST ─────────────┼─▶ RAG server :7003  /rag/query, /rag/documents
                                                               ┊        │                  │
                                       ollama:11434 (Compose) ◀┼────────┴──────────────────┘
```

The frontend never talks to the database or the shared services, and the backend never opens the
SQLite file — each microservice is independently containerised and independently deployable.
Containers reach the host services through `host.docker.internal` (see `docker-compose.yml`).

## API (as registered on the Group Registration Form)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/products` | List products (`?sku=` `?category=` `?status=` `?search=` `?sort=`) |
| POST | `/api/products` | Create a product |
| GET | `/api/products/<id>` | Read one product |
| PUT | `/api/products/<id>` | Update a product (partial payloads allowed) |
| DELETE | `/api/products/<id>` | Delete a product |
| POST | `/api/products/ai` | AI description + price suggestion |
| GET | `/api/categories` | Categories with counts and average price |
| POST | `/api/products/<id>/mcp-check` | **R1** MCP `check_product_listing` for one product |
| POST | `/api/catalogue/ask` | **R1** Grounded RAG answer (`{"question": "..."}`) |
| POST | `/api/catalogue/rag-sync` | **R1** Re-index every product into the shared RAG corpus (API only; used by the validation script) |
| GET | `/health` | Service health: database, AI-Mode, MCP server and RAG server |

Example:

```bash
curl http://localhost:8001/api/products?category=Audio

curl -X POST http://localhost:8001/api/products \
  -H 'Content-Type: application/json' \
  -d '{"sku":"SKU-AUD-1004","name":"Cadence Earbuds","category":"Audio","price":89.95}'

curl -X POST http://localhost:8001/api/products/ai \
  -H 'Content-Type: application/json' \
  -d '{"name":"Cadence Earbuds","category":"Audio","keywords":"waterproof, 8h battery"}'
```

## Database

`products (id, sku, name, description, category, price, status, created_at, updated_at)`

* `sku` is unique; `status` is `active` / `draft` / `archived`; `updated_at` is maintained by a trigger.
* Seeded with **12 records** across four categories (the specification requires at least ten).
* Reset any time with `curl -X POST http://localhost:9001/admin/reseed`.

## Plan → Act → Observe → Adapt

`POST /api/products/ai` is this feature's implementation of the team's shared agentic loop:

1. **Plan** — `backend/app/ai_agent.py` queries `GET /stats/category/<category>` on the database
   microservice and grounds the prompt in real facts: how many products the category holds, its
   average / minimum / maximum price, and up to five comparable products.
2. **Act** — AI-Mode calls the approved open-source LLM through the Ollama runtime.
3. **Observe** — the answer must be valid JSON with a 20–60 word description and a price between
   $1 and $9,999; anything else is a violation.
4. **Adapt** — AI-Mode re-prompts with the exact violations. If the retry budget runs out, the
   backend's deterministic fallback (category average price + a clearly-labelled description) is
   returned, so the catalogue UI never breaks.

The full trace is rendered in the AI panel of the UI — screenshot it for the technical report.
Nothing is written to the database until the student presses **Apply to the form** and then
**Create product**, which is the human-review step of the loop.

## Release 1 – shared MCP and RAG

### MCP: `check_product_listing`

1. The frontend's **Check** button (one per table row) posts to `/products/<id>/mcp-check`.
2. The backend reads the product and the other products in its category from the database
   microservice, and grounds the tool with `comparable_count` / avg / min / max prices
   (excluding the product itself).
3. It calls the tool over genuine MCP Streamable HTTP (`mcp` SDK client → `:7002/mcp`).
4. The result is checked against the tool contract (`backend/app/mcp_client.py`) before the UI
   renders it: `listing_status` (`ready` / `needs_attention` / `invalid`), `price_position`,
   `price_vs_average_pct`, and the `issues` / `warnings` / `errors` lists.

Tool boundaries: the tool is pure and read-only. It receives no database address or credential
and never writes a product or changes a price. Arguments outside its declared schema are
rejected by the MCP layer before the tool runs. Contract: `ai-services/mcp-server/tool-contracts.md`.

### RAG: grounded catalogue answers

Knowledge sources, both tagged `feature: product_catalogue`:

| Source | How it reaches the corpus |
|---|---|
| `ai-services/rag-server/knowledge/product-catalogue-policy.md` (7 sections) | indexed by the RAG server on its first query |
| live product records (`catalogue:product:<id>`) | pushed by this backend on create / update / delete, and before the first question each process handles |

Every query is filtered to `product_catalogue`, so another feature's sources are never cited.
The backend rejects any answer that has no citations, an unknown confidence, or a foreign
source. When nothing relevant is retrieved the UI shows **Insufficient context** and no answer.
Confidence comes from how many sources support the answer (3+ high, 1–2 medium), never from
the model's self-assessment.

### Agentic loop validation modes

`student-1/validation/validate_release1.py` runs the shared loop's validation modes from the
terminal: it sends a real MCP tool result and real RAG answers, produced through this
backend/API, to AI-Mode `POST /agent/validate` (`mode: "mcp"` / `"rag"`) and saves each verdict
with its Plan → Act → Observe → Adapt trace to `docs/evidence/student-1/19`–`21`.

### Switches

| Variable | Default | CI |
|---|---|---|
| `AI_MODE_ENABLED` / `MCP_ENABLED` / `RAG_ENABLED` | `true` | `false` |
| `AI_MODE_URL` / `MCP_SERVER_URL` / `RAG_SERVER_URL` | `http://host.docker.internal:7001` / `:7002` / `:7003` | unused |

When disabled, the MCP and RAG endpoints answer `503 … integration is disabled`, `/health`
reports `{"status": "disabled"}` for each, and the AI copy assistant returns its deterministic
fallback.

## Running

Whole stack (recommended), from the repository root:

```bash
cp .env.example .env
docker compose up -d --build         # containerised features + Ollama
bash scripts/run-ai-services.sh      # native AI-Mode :7001, MCP :7002, RAG :7003
python student-1/validation/validate_release1.py   # Release 1 checks -> docs/evidence/student-1/
```

Just these three microservices, without Docker:

```bash
pip install -r database/requirements.txt -r backend/requirements.txt -r frontend/requirements.txt

DB_PATH=./data/products.db python database/app.py                    # :9001
DATABASE_URL=http://localhost:9001 AI_MODE_URL=http://localhost:7001 \
  MCP_SERVER_URL=http://localhost:7002 RAG_SERVER_URL=http://localhost:7003 \
  python backend/wsgi.py                                             # :8001
BACKEND_URL=http://localhost:8001 python frontend/app.py             # :3001
```

## Tests

```bash
pytest student-1/tests -v      # 112 tests: no Docker, LLM, MCP or RAG server required
```

`tests/` covers the SQLite layer and the database HTTP API, the backend's CRUD contract and every
validation rule, the AI request the backend builds (grounding + guardrails + fallback), and the
frontend's HTMX partials. Release 1 adds `test_mcp_rag_backend.py` (MCP grounding and contract
checks against the real shared tool; RAG citations, confidence, insufficient context and foreign
sources; CRUD-to-corpus sync; disabled mode) and
`test_mcp_rag_frontend.py` (what the UI renders for each outcome). Downstream services are
stubbed so the suite runs in GitHub Actions.

CI: `.github/workflows/student-1.yml` runs with `AI_MODE_ENABLED`, `MCP_ENABLED` and
`RAG_ENABLED` set to `false`: lint, unit tests (Student 1, AI-Mode, MCP server, RAG server),
a check that AI-Mode, MCP and RAG are not Compose services, Docker builds, then a container
smoke test of the CRUD path plus proof that the MCP and RAG endpoints are present but disabled.

