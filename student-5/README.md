# Student 5 — Alexander McGuinn — Reviews and Ratings

Status: **Implemented.**

Lets customers submit ratings and reviews for products in the catalogue, and summarises a
product's reviews into pros and cons with AI.

## Microservices

| Microservice | Folder | Port | Stack |
|---|---|---|---|
| Frontend | `frontend/` | 3005 | Flask + HTMX + shared CSS theme |
| Backend / API | `backend/` | 8005 | Flask REST API |
| Database | `database/` | 9005 | SQLite behind a small Flask data API |

```
browser ──HTMX──▶ frontend:3005 ──REST──▶ backend:8005 ──REST──▶ database:9005 (SQLite)
                                              │              │
                                              │              └──REST──▶ student-1-backend:8001 (product names)
                                              └──REST──▶ ai-mode:7000 ──▶ ollama:11434 ──▶ LLM
```

The frontend never talks to the database, and the backend never opens the SQLite file - each
microservice is independently containerised and independently deployable. Product names are
looked up from Student 1's Product Catalogue API by SKU on a best-effort basis; if that service
is unreachable, the raw SKU is shown instead.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/reviews` | List reviews (`?product_sku=` `?user_id=` `?rating=` `?sort=`) |
| POST | `/api/reviews` | Create a review |
| GET | `/api/reviews/<id>` | Read one review |
| PUT | `/api/reviews/<id>` | Update a review (partial payloads allowed) |
| DELETE | `/api/reviews/<id>` | Delete a review |
| POST | `/api/reviews/ai` | AI summary, pros and cons for one product's reviews |
| GET | `/api/products` | Products available to review (proxied from Student 1) |
| GET | `/health` | Service health, including the database and AI-Mode |

Example:

```bash
curl http://localhost:8005/api/reviews?product_sku=SKU-AUD-1001

curl -X POST http://localhost:8005/api/reviews \
  -H 'Content-Type: application/json' \
  -d '{"product_sku":"SKU-AUD-1001","user_id":"customer-42","rating":5,"review":"Great headphones."}'

curl -X POST http://localhost:8005/api/reviews/ai \
  -H 'Content-Type: application/json' \
  -d '{"product_sku":"SKU-AUD-1001"}'
```

## Database

`reviews (review_id UUID PK, product_sku, user_id UUID, rating 1-5, review, created_at)`

* `product_sku` links a review to a product in Student 1's catalogue (the same cross-service
  pattern Student 2 uses for order lines); `rating` is constrained to 1-5.
* Seeded with **12 records** across eight products (the specification requires at least ten).
* Reset any time with `curl -X POST http://localhost:9005/admin/reseed`.

## Plan → Act → Observe → Adapt

`POST /api/reviews/ai` is this feature's implementation of the team's shared agentic loop:

1. **Plan** — `backend/app/ai_agent.py` queries `GET /stats/product/<sku>` on the database
   microservice and grounds the prompt in real facts: how many reviews the product has, its
   average rating, the rating distribution, and a sample of the highest- and lowest-rated review
   text.
2. **Act** — AI-Mode calls the approved open-source LLM through the Ollama runtime.
3. **Observe** — the answer must be valid JSON with a short summary plus pros and cons, each
   within a word budget; anything else is a violation.
4. **Adapt** — AI-Mode re-prompts with the exact violations. If the retry budget runs out, the
   backend's deterministic fallback (grounded in the rating distribution) is returned, so the
   product page never breaks - including when a product has no reviews yet.

The full trace is rendered in the AI panel of the UI — screenshot it for the technical report.

## Running

Whole stack (recommended):

```bash
docker compose up --build            # from the repository root
```

Just these three microservices, without Docker:

```bash
pip install -r database/requirements.txt -r backend/requirements.txt -r frontend/requirements.txt

DB_PATH=./data/reviews.db python database/app.py                                          # :9005
DATABASE_URL=http://localhost:9005 AI_MODE_URL=http://localhost:7000 \
  CATALOGUE_URL=http://localhost:8001 python backend/wsgi.py                              # :8005
BACKEND_URL=http://localhost:8005 python frontend/app.py                                  # :3005
```

## Tests

```bash
pytest student-5/tests -v      # 48 tests, no Docker and no LLM required
```

`tests/` covers the SQLite layer and the database HTTP API, the backend's CRUD contract and every
validation rule, the AI request the backend builds (grounding + guardrails + fallback), and the
frontend's HTMX partials. Downstream services (the database HTTP API, Student 1's catalogue, and
AI-Mode) are all stubbed so the suite runs in GitHub Actions.

CI: `.github/workflows/student-5.yml` — lint, unit tests, Docker builds, then a container smoke
test that exercises the real CRUD path end to end.
