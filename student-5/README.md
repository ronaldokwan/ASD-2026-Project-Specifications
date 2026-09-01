# Student 5 — Alexander McGuinn — Reviews and Ratings

Status: **skeleton only — not implemented.**

Let users submit ratings and reviews for products in the catalogue.

## What to build

| Microservice  | Folder      | Port | Stack                                |
| ------------- | ----------- | ---- | ------------------------------------ |
| Frontend      | `frontend/` | 3005 | Flask + HTMX + the shared CSS theme  |
| Backend / API | `backend/`  | 8005 | Flask REST API                       |
| Database      | `database/` | 9005 | SQLite behind a small Flask data API |

- **Frontend functions:** View reviews, add a review for a product, a review list with star displays, and an AI summary of a product's reviews.
- **Backend/API functions:** CRUD on `/api/reviews`; AI summarisation and analysis of a product's reviews into pros and cons.
- **Database tables:** `reviews (review_id UUID PK, rating 1-5, review TEXT, created_at, user_id UUID FK)` — seed **at least 10 records**.

## Use Student 1 as the reference implementation

`student-1/` is a complete, working example of exactly this structure. The fastest route:

```bash
cp -r student-1/database  student-5/database
cp -r student-1/backend   student-5/backend
cp -r student-1/frontend  student-5/frontend
cp -r student-1/tests     student-5/tests
```

Then work through this checklist:

- [ ] `database/schema.sql` + `database/seed.sql` — your tables, 10+ seed records
- [ ] `database/db.py` / `database/app.py` — your queries, ports `9005`, `DB_PATH=/data/reviews.db`
- [ ] `backend/app/validation.py` — your business rules
- [ ] `backend/app/routes.py` — your endpoints, port `8005`
- [ ] `backend/app/ai_agent.py` — your AI task: Summarise a product's reviews into pros and cons, grounded in the stored reviews.
- [ ] `frontend/` templates — your screens, port `3005`, keep `/shared/css/theme.css`
- [ ] `tests/` — adapt the fixtures; keep every downstream hop stubbed so CI needs no Docker
- [ ] `docker-compose.yml` — uncomment and renumber your three services (root of the repo)
- [ ] `shared/config/services.json` — change your feature's `status` to `"ready"`
- [ ] `.github/workflows/student-5.yml` — copy the steps from `student-1.yml`

## Rules that apply to every feature

- All AI calls go through the shared AI-Mode service (`ai-services/ai-mode/`), never straight to
  Ollama — that is what makes the whole application share one Plan → Act → Observe → Adapt loop.
- Ground the prompt in real facts from **your own** database microservice, declare guardrails in
  `output_schema`, and always supply a `fallback`.
- Link the shared theme (`/shared/css/theme.css`) so the integrated UI stays consistent.
- Your feature must be reachable from the unified home page (`shared/index.html`).
- Work on a branch, open a Pull Request, and stay inside `student-5/`.
