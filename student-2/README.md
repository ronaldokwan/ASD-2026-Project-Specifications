# Student 2 — Jinying Li — Customer Orders

Status: **skeleton only — not implemented.**

Create, view, update, cancel and track customer orders containing one or more products.

## What to build

| Microservice  | Folder      | Port | Stack                                |
| ------------- | ----------- | ---- | ------------------------------------ |
| Frontend      | `frontend/` | 3002 | Flask + HTMX + the shared CSS theme  |
| Backend / API | `backend/`  | 8002 | Flask REST API                       |
| Database      | `database/` | 9002 | SQLite behind a small Flask data API |

- **Frontend functions:** View and filter orders by status; create and edit orders; add or remove order lines; cancel orders; show product names, quantities, prices and totals; generate AI order summaries and shipping-delay emails.
- **Backend/API functions:** CRUD APIs for orders and order lines; filter by status or customer email; validate orders and calculate totals; look up product names from the Student 1 catalogue API by SKU (fall back to the raw SKU); AI order summaries and shipping-delay emails.
- **Database tables:** `orders (order_number, customer_email, status, ordered_at)` and `order_lines (order_id, sku, quantity, unit_price)` — seed **at least 10 records**.

## Use Student 1 as the reference implementation

`student-1/` is a complete, working example of exactly this structure. The fastest route:

```bash
cp -r student-1/database  student-2/database
cp -r student-1/backend   student-2/backend
cp -r student-1/frontend  student-2/frontend
cp -r student-1/tests     student-2/tests
```

Then work through this checklist:

- [ ] `database/schema.sql` + `database/seed.sql` — your tables, 10+ seed records
- [ ] `database/db.py` / `database/app.py` — your queries, ports `9002`, `DB_PATH=/data/orders.db`
- [ ] `backend/app/validation.py` — your business rules
- [ ] `backend/app/routes.py` — your endpoints, port `8002`
- [ ] `backend/app/ai_agent.py` — your AI task: Summarise a customer's order history / draft a shipping-delay email, grounded in that customer's real orders.
- [ ] `frontend/` templates — your screens, port `3002`, keep `/shared/css/theme.css`
- [ ] `tests/` — adapt the fixtures; keep every downstream hop stubbed so CI needs no Docker
- [ ] `docker-compose.yml` — uncomment and renumber your three services (root of the repo)
- [ ] `shared/config/services.json` — change your feature's `status` to `"ready"`
- [ ] `.github/workflows/student-2.yml` — copy the steps from `student-1.yml`

## Rules that apply to every feature

- All AI calls go through the shared AI-Mode service (`ai-services/ai-mode/`), never straight to
  Ollama — that is what makes the whole application share one Plan → Act → Observe → Adapt loop.
- Ground the prompt in real facts from **your own** database microservice, declare guardrails in
  `output_schema`, and always supply a `fallback`.
- Link the shared theme (`/shared/css/theme.css`) so the integrated UI stays consistent.
- Your feature must be reachable from the unified home page (`shared/index.html`).
- Work on a branch, open a Pull Request, and stay inside `student-2/`.
