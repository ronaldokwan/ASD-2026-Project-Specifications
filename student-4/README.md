# Student 4 — Jonathan Czesler — Inventory and Stock

Status: **implemented.**

Monitor warehouse inventory and keep stock at optimal levels, with AI restocking advice.

## What to build

| Microservice  | Folder      | Port | Stack                                |
| ------------- | ----------- | ---- | ------------------------------------ |
| Frontend      | `frontend/` | 3004 | Flask + HTMX + the shared CSS theme  |
| Backend / API | `backend/`  | 8004 | Flask REST API                       |
| Database      | `database/` | 9004 | SQLite behind a small Flask data API |

- **Frontend functions:** Low-stock alerts, a visual low-stock indicator on product lookups, AI restocking advice, per-item MCP reorder checks, and inventory-grounded RAG questions.
- **Backend/API functions:** CRUD on `/api/stock`, plus `GET /api/stock/low`; AI advice, shared MCP reorder checks, and shared RAG answers.
- **Database tables:** `stock (product_id, product_name, sku, quantity, location, restock_threshold, last_restock)` — seed **at least 10 records**.

## Use Student 1 as the reference implementation

`student-1/` is a complete, working example of exactly this structure. The fastest route:

```bash
cp -r student-1/database  student-4/database
cp -r student-1/backend   student-4/backend
cp -r student-1/frontend  student-4/frontend
cp -r student-1/tests     student-4/tests
```

Then work through this checklist:

- [x] `database/schema.sql` + `database/seed.sql` — stock table and 10+ seed records
- [x] `database/db.py` / `database/app.py` — stock queries, port `9004`, `DB_PATH=/data/stock.db`
- [x] `backend/app/validation.py` — inventory business rules
- [x] `backend/app/routes.py` — stock CRUD and restock endpoints on port `8004`
- [x] `backend/app/ai_agent.py` — grounded AI restocking recommendations
- [x] shared MCP `check_stock_reorder` tool — deterministic reorder check from caller-supplied stock facts
- [x] backend MCP/RAG clients — MCP assessment plus feature-tagged inventory documents and grounded answers
- [x] `frontend/` templates — inventory screens on port `3004`, using `/shared/css/theme.css`
- [x] `tests/` — adapted stock fixtures with downstream hops stubbed
- [x] `docker-compose.yml` — Student 4 database, backend, and frontend services
- [x] `shared/config/services.json` — Student 4 marked `"ready"`
- [x] `.github/workflows/student-4.yml` — test, build, and smoke-test workflow

## Rules that apply to every feature

- AI restocking advice goes through shared AI-Mode (`ai-services/ai-mode/`); grounded questions use
  the shared RAG service. Neither student-4 service calls Ollama directly.
- Ground the prompt in real facts from **your own** database microservice, declare guardrails in
  `output_schema`, and always supply a `fallback`.
- Link the shared theme (`/shared/css/theme.css`) so the integrated UI stays consistent.
- Your feature must be reachable from the unified home page (`shared/index.html`).
- MCP reorder checks call the shared `check_stock_reorder` tool; inventory RAG documents use
  `metadata.feature=inventory_stock` and are synchronized best-effort after writes.
- Keep student-specific changes inside `student-4/`. Shared MCP tool changes must be coordinated
  with the team and kept to the shared tool contract, implementation, registration, and tests.
- Work on a branch and open a Pull Request.
