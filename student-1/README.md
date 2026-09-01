# Student 1 — Ronaldo Kwan — Product Catalogue

Status: **Implemented.**

Provides the store's product catalogue: browse and filter products by category, full CRUD, and an
AI assistant that drafts a product description and suggests a price grounded in what comparable
products in the same category already cost.

## Microservices

| Microservice | Folder | Port | Stack |
|---|---|---|---|
| Frontend | `frontend/` | 3001 | Flask + HTMX + shared CSS theme |
| Backend / API | `backend/` | 8001 | Flask REST API |
| Database | `database/` | 9001 | SQLite behind a small Flask data API |

```
browser ──HTMX──▶ frontend:3001 ──REST──▶ backend:8001 ──REST──▶ database:9001 (SQLite)
                                              │
                                              └──REST──▶ ai-mode:7000 ──▶ ollama:11434 ──▶ LLM
```

The frontend never talks to the database, and the backend never opens the SQLite file — each
microservice is independently containerised and independently deployable.

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
| GET | `/health` | Service health, including the database and AI-Mode |

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

## Running

Whole stack (recommended):

```bash
docker compose up --build            # from the repository root
```

Just these three microservices, without Docker:

```bash
pip install -r database/requirements.txt -r backend/requirements.txt -r frontend/requirements.txt

DB_PATH=./data/products.db python database/app.py                    # :9001
DATABASE_URL=http://localhost:9001 AI_MODE_URL=http://localhost:7000 python backend/wsgi.py   # :8001
BACKEND_URL=http://localhost:8001 python frontend/app.py             # :3001
```

## Tests

```bash
pytest student-1/tests -v      # 47 tests, no Docker and no LLM required
```

`tests/` covers the SQLite layer and the database HTTP API, the backend's CRUD contract and every
validation rule, the AI request the backend builds (grounding + guardrails + fallback), and the
frontend's HTMX partials. Downstream services are stubbed so the suite runs in GitHub Actions.

CI: `.github/workflows/student-1.yml` — lint, unit tests, Docker builds, then a container smoke
test that exercises the real CRUD path end to end.

