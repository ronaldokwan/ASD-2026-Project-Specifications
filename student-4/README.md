# Student 4 — Jonathan Czesler — Inventory and Stock

Status: **skeleton only — not implemented.**

Monitor warehouse inventory and keep stock at optimal levels, with AI restocking advice.

## What to build

| Microservice  | Folder      | Port | Stack                                |
| ------------- | ----------- | ---- | ------------------------------------ |
| Frontend      | `frontend/` | 3004 | Flask + HTMX + the shared CSS theme  |
| Backend / API | `backend/`  | 8004 | Flask REST API                       |
| Database      | `database/` | 9004 | SQLite behind a small Flask data API |

- **Frontend functions:** Low-stock alerts, a visual low-stock indicator on product lookups, and AI restocking advice on demand.
- **Backend/API functions:** CRUD on `/api/stock`, plus `GET /api/stock/low`; AI advice on what to reorder.
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

- [ ] `database/schema.sql` + `database/seed.sql` — your tables, 10+ seed records
- [ ] `database/db.py` / `database/app.py` — your queries, ports `9004`, `DB_PATH=/data/stock.db`
- [ ] `backend/app/validation.py` — your business rules
- [ ] `backend/app/routes.py` — your endpoints, port `8004`
- [ ] `backend/app/ai_agent.py` — your AI task: Read warehouse stock levels and recommend what to reorder and in what quantity.
- [ ] `frontend/` templates — your screens, port `3004`, keep `/shared/css/theme.css`
- [ ] `tests/` — adapt the fixtures; keep every downstream hop stubbed so CI needs no Docker
- [ ] `docker-compose.yml` — uncomment and renumber your three services (root of the repo)
- [ ] `shared/config/services.json` — change your feature's `status` to `"ready"`
- [ ] `.github/workflows/student-4.yml` — copy the steps from `student-1.yml`

## Rules that apply to every feature

- All AI calls go through the shared AI-Mode service (`ai-services/ai-mode/`), never straight to
  Ollama — that is what makes the whole application share one Plan → Act → Observe → Adapt loop.
- Ground the prompt in real facts from **your own** database microservice, declare guardrails in
  `output_schema`, and always supply a `fallback`.
- Link the shared theme (`/shared/css/theme.css`) so the integrated UI stays consistent.
- Your feature must be reachable from the unified home page (`shared/index.html`).
- Work on a branch, open a Pull Request, and stay inside `student-4/`.
