# Student 3 — Customer Account Management

Status: **Release 1 MCP and RAG extension implemented on top of Release 0.**

Provides staff-facing customer record management: list and search customers, add/view/edit/delete
records, manually select Bronze/Silver/Gold loyalty tiers, and request a grounded AI reward
suggestion. Release 0 intentionally has no signup, login, passwords, roles, sessions, access
restrictions, email sending, order integration, or automatic reward application.

Release 1 adds an admin-triggered MCP profile check and grounded loyalty-policy
questions. Neither interaction changes customer records.

## Services

| Service | Folder | Port | Stack |
|---|---|---:|---|
| Frontend | `frontend/` | 3003 | Flask, Jinja, HTMX, shared CSS |
| Backend/API | `backend/` | 8003 | Flask REST API |
| Database API | `database/` | 9003 | Flask API over SQLite |

```text
browser -> frontend:3003 -> backend:8003 -> database:9003 -> SQLite
                              |-> native AI-Mode:7001 -> Ollama -> LLM
                              |-> native MCP:7002/mcp -> check_customer_profile
                              +-> native RAG:7003 -> Chroma -> Ollama
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
| POST | `/api/customers/<id>/mcp-profile` | Run the registered privacy-minimised MCP profile tool |
| POST | `/api/loyalty-benefits/ask` | Ask a grounded question about the loyalty policy |

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

## MCP profile check

The backend retrieves the selected customer, but sends the MCP tool only their
tier, joining date, two completeness booleans, and the calculation date. It
never sends the name, email, phone value or address value. The backend uses the
official `mcp==2.2.0` client over Streamable HTTP and strictly validates the
structured tool result before returning it to the frontend.

## RAG loyalty-policy questions

`ai-services/rag-server/knowledge/customer-loyalty-policy.md` is a checked-in,
sectioned knowledge source aligned with the Release 0 reward options. Queries
are forced into the `customer_accounts` feature namespace. The UI renders the
grounded answer, source filename and section, and confidence, or a separate
insufficient-context/service-unavailable state. Model output is escaped and is
never stored in the Customer database.

## Run and test

From the repository root:

```bash
docker compose up --build student-3-db student-3-backend student-3-frontend
pytest student-3/tests -v
```

Start the non-containerised services separately after Ollama is ready:

```bash
bash scripts/run-ai-services.sh
```

MCP is available at `http://localhost:7002/mcp`; RAG is available at
`http://localhost:7003`. Set `AI_MODE_ENABLED=false`, `MCP_ENABLED=false` and
`RAG_ENABLED=false` for CI/offline operation. Release 0 AI then uses its
existing deterministic fallback, while MCP/RAG endpoints report unavailable.

Open <http://localhost:3003>.
