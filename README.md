# ASD 2026 – Agentic AI Retail Application (Canvas Group 40)

An Agentic AI retail application built as a **microservices architecture**, containerised with
Docker, and delivered incrementally across Releases 0, 1 and 2.

| Item          | Value                                                          |
| ------------- | -------------------------------------------------------------- |
| Canvas Group  | 40                                                             |
| Team Leader   | Ronaldo Kwan (ronaldo.kwan@student.uts.edu.au)                 |
| Topic         | Agentic AI Retail Application                                  |
| Approved LLMs | `qwen2.5:0.5b`, `llama3.1:8b`, `deepseek-r1:8b` (via Ollama)   |
| Repository    | https://github.com/ronaldokwan/ASD-2026-Project-Specifications |

## Team and features

| #   | Student                             | Feature                              | Status          |
| --- | ----------------------------------- | ------------------------------------ | --------------- |
| 1   | Ronaldo Kwan                        | Product Catalogue                    | **Implemented** |
| 2   | Jinying Li                          | Customer Orders                      | Skeleton only   |
| 3   | Vishvak Ananthakrishnan Rameshkumar | Customer Account Management          | **Implemented** |
| 4   | Jonathan Czesler                    | Inventory and Stock                  | Skeleton only   |
| 5   | Alexander McGuinn                   | Reviews and Ratings                  | Skeleton only   |

Each student owns **three microservices** (frontend, backend/API, database) plus their own
`.github/workflows/student-N.yml` CI/CD workflow.

## Repository structure

```
.
├── .github/workflows/        # student-1.yml … student-5.yml
├── ai-services/              # shared AI services
│   └── ai-mode/              # AI-Mode: Plan → Act → Observe → Adapt loop over Ollama
├── docs/                     # diagrams, reports, evidence
├── scripts/                  # build / run / seed / test scripts
├── shared/                   # unified home page, shared CSS/JS/assets, service registry
├── student-1/ … student-5/   # each student's frontend + backend + database + tests + Docker
├── docker-compose.yml        # one shared multi-container configuration for the whole team
├── .env.example
└── README.md
```

## Port map

| Service                    | URL                    | Owner     |
| -------------------------- | ---------------------- | --------- |
| Unified home page          | http://localhost:3000  | Team      |
| Ollama runtime             | http://localhost:11434 | Team      |
| AI-Mode service            | http://localhost:7001  | Team      |
| Product Catalogue frontend | http://localhost:3001  | Student 1 |
| Product Catalogue API      | http://localhost:8001  | Student 1 |
| Product Catalogue database | http://localhost:9001  | Student 1 |
| Customer Orders            | 3002 / 8002 / 9002     | Student 2 |
| Customer Accounts          | 3003 / 8003 / 9003     | Student 3 |
| Inventory and Stock        | 3004 / 8004 / 9004     | Student 4 |
| Reviews and Ratings        | 3005 / 8005 / 9005     | Student 5 |

## Quick start (local deployment)

Prerequisites: Docker Desktop, Git. (Ollama runs **inside** Docker – no host install needed.)

```bash
cp .env.example .env
docker compose up --build
```

First start pulls the LLM (`qwen2.5:0.5b`, ~400 MB) into the `ollama-data` volume – this takes a
few minutes once. Then open:

- http://localhost:3000 – unified home page
- http://localhost:3001 – Product Catalogue (Student 1)

Helper scripts (run from Git Bash on Windows):

```bash
bash scripts/run-local.sh     # build + start the whole stack, then print the URLs
bash scripts/pull-model.sh    # (re)pull an approved LLM into the running Ollama container
bash scripts/run-tests.sh     # pytest for every implemented student, with JUnit evidence
```

Everything else is a plain Docker command:

```bash
docker compose down             # stop the stack (add -v to wipe the database and model)
curl -X POST http://localhost:9001/admin/reseed   # reset the catalogue to its 12 seed records
```

## Agentic AI workflow – Plan → Act → Observe → Adapt

The shared loop lives in `ai-services/ai-mode/` and is called by every student backend.

1. **Plan** – build a grounded prompt from the caller's goal + context facts pulled from that
   student's database microservice (e.g. average price of the product category).
2. **Act** – call the approved open-source LLM through the Ollama runtime.
3. **Observe** – parse and validate the model output against the caller's schema and guardrails.
4. **Adapt** – on a failed observation, re-prompt with the specific violation; after
   `AI_MODE_MAX_ADAPT_ATTEMPTS` attempts fall back to a deterministic result so the UI never breaks.

Every response returns the full `trace` of the four steps, which the UI renders and the technical
report screenshots as evidence.

## Contributing

- `main` is the integration branch – never commit to it directly.
- Branch per feature: `student-1/product-catalogue-crud`.
- Open a Pull Request, resolve conflicts, get one teammate's review, then merge.
- Stay inside your own `student-N/` folder; changes to `shared/`, `ai-services/`,
  `docker-compose.yml` must be agreed by the team.
