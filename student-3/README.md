# Student 3 — Customer Account Management

Status: **implemented for Release 0.**

Provides staff-facing customer record management: list and search customers, add/view/edit/delete
records, manually select Bronze/Silver/Gold loyalty tiers, and request a grounded AI reward
suggestion. Release 0 intentionally has no signup, login, passwords, roles, sessions, access
restrictions, email sending, order integration, or automatic reward application.

## Services

| Service | Folder | Port | Stack |
|---|---|---:|---|
| Frontend | `frontend/` | 3003 | Flask, Jinja, HTMX, shared CSS |
| Backend/API | `backend/` | 8003 | Flask REST API |
| Database API | `database/` | 9003 | Flask API over SQLite |

```text
browser -> frontend:3003 -> backend:8003 -> database:9003 -> SQLite
                              |
                              +-> ai-mode:7000 -> Ollama -> LLM
```

Only the database service opens `/data/customers.db`. The other services communicate over HTTP.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Backend and dependency health |
| GET | `/api/customers` | List customers; optional `?search=` matches name/email |
| POST | `/api/customers` | Create a customer |
| GET | `/api/customers/<id>` | Read one customer |
| PUT | `/api/customers/<id>` | Partially update a customer |
| DELETE | `/api/customers/<id>` | Delete a customer |
| POST | `/api/customers/<id>/ai-reward` | Generate a non-persistent loyalty reward suggestion |

## Data and validation

`customers(id, name, email, phone, address, loyalty_tier, joined_at)`

- Email is normalized to lowercase and uniquely indexed case-insensitively.
- Loyalty tier is restricted to `Bronze`, `Silver`, or `Gold` and is manually selected.
- Joining dates use ISO `YYYY-MM-DD` format.
- Phone and address are optional.
- Twelve fictional `.example.test` customers are seeded on an empty database.

## AI reward workflow

The backend retrieves the selected customer and sends only their stored name, loyalty tier, and
joining date to shared AI-Mode. The output schema contains two validated strings: `reward` and
`reason`. Transport failures and exhausted AI retries return a deterministic tier-based fallback.
Suggestions are displayed with the workflow trace and are never stored, applied, or emailed.

## Run and test

From the repository root:

```bash
docker compose up --build student-3-db student-3-backend student-3-frontend
pytest student-3/tests -v
```

Open <http://localhost:3003>.
