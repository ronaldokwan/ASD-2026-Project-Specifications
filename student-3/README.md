# Student 3 — Vishvak Ananthakrishnan Rameshkumar — Customer Account and Access Management

Status: **skeleton only — not implemented.**

Let customers register, log in and manage their profiles, and let administrators manage accounts.

## What to build

| Microservice  | Folder      | Port | Stack                                |
| ------------- | ----------- | ---- | ------------------------------------ |
| Frontend      | `frontend/` | 3003 | Flask + HTMX + the shared CSS theme  |
| Backend / API | `backend/`  | 8003 | Flask REST API                       |
| Database      | `database/` | 9003 | SQLite behind a small Flask data API |

- **Frontend functions:** Signup, login and logout; view, edit and delete profile; admin customer list and search; add, edit and delete accounts; generate an AI loyalty-reward suggestion.
- **Backend/API functions:** Authentication, customer CRUD and search APIs, password hashing, role-based access, database API communication, and AI loyalty-reward suggestions.
- **Database tables:** `customers (id, name, email, password_hash, phone, address, role, loyalty_tier, joined_at)` — seed **at least 10 records**.

## Use Student 1 as the reference implementation

`student-1/` is a complete, working example of exactly this structure. The fastest route:

```bash
cp -r student-1/database  student-3/database
cp -r student-1/backend   student-3/backend
cp -r student-1/frontend  student-3/frontend
cp -r student-1/tests     student-3/tests
```

Then work through this checklist:

- [ ] `database/schema.sql` + `database/seed.sql` — your tables, 10+ seed records
- [ ] `database/db.py` / `database/app.py` — your queries, ports `9003`, `DB_PATH=/data/customers.db`
- [ ] `backend/app/validation.py` — your business rules
- [ ] `backend/app/routes.py` — your endpoints, port `8003`
- [ ] `backend/app/ai_agent.py` — your AI task: Suggest a loyalty reward, grounded in the customer's tier and history.
- [ ] `frontend/` templates — your screens, port `3003`, keep `/shared/css/theme.css`
- [ ] `tests/` — adapt the fixtures; keep every downstream hop stubbed so CI needs no Docker
- [ ] `docker-compose.yml` — uncomment and renumber your three services (root of the repo)
- [ ] `shared/config/services.json` — change your feature's `status` to `"ready"`
- [ ] `.github/workflows/student-3.yml` — copy the steps from `student-1.yml`

## Rules that apply to every feature

- All AI calls go through the shared AI-Mode service (`ai-services/ai-mode/`), never straight to
  Ollama — that is what makes the whole application share one Plan → Act → Observe → Adapt loop.
- Ground the prompt in real facts from **your own** database microservice, declare guardrails in
  `output_schema`, and always supply a `fallback`.
- Link the shared theme (`/shared/css/theme.css`) so the integrated UI stays consistent.
- Your feature must be reachable from the unified home page (`shared/index.html`).
- Work on a branch, open a Pull Request, and stay inside `student-3/`.
