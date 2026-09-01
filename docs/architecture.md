# Architecture

Diagrams are written in Mermaid so they render on GitHub. Export them to PNG into
`docs/diagrams/` before pasting them into the technical report.

## 1. Integrated architecture

```mermaid
flowchart TB
  subgraph Browser
    HOME["Unified home page<br/>shared/index.html : 3000"]
  end

  subgraph S1["Student 1 · Ronaldo Kwan · Product Catalogue"]
    F1["Frontend<br/>HTMX + Flask : 3001"]
    B1["Backend / API<br/>Flask REST : 8001"]
    D1[("Database<br/>SQLite : 9001")]
  end

  subgraph S2to5["Students 2–5 · not implemented yet"]
    REST["Customer Orders · Accounts · Inventory · Reviews<br/>300N / 800N / 900N"]
  end

  subgraph AI["Shared AI services"]
    AM["AI-Mode<br/>Plan → Act → Observe → Adapt : 7000"]
    OL["Ollama runtime : 11434"]
    LLM["qwen2.5:0.5b / llama3.1:8b / deepseek-r1:8b"]
  end

  HOME --> F1
  HOME -.-> REST
  F1 -->|REST| B1
  B1 -->|REST| D1
  B1 -->|REST| AM
  REST -.-> AM
  AM --> OL --> LLM
```

Every box is its own container; the whole diagram is one `docker-compose.yml`.

## 2. Student 1 microservice detail

```mermaid
sequenceDiagram
  participant U as User (browser)
  participant F as Frontend :3001
  participant B as Backend/API :8001
  participant D as Database :9001
  participant A as AI-Mode :7000
  participant O as Ollama + LLM

  U->>F: HTMX POST /ai/suggest (name, category)
  F->>B: POST /api/products/ai
  B->>D: GET /stats/category/Audio        %% Plan: ground the prompt
  D-->>B: count, avg / min / max price, comparable products
  B->>A: POST /agent/run (task, context, output_schema, fallback)
  A->>O: generate(prompt)                  %% Act
  O-->>A: JSON answer
  A->>A: validate against the schema       %% Observe
  A->>O: re-prompt with the violations     %% Adapt (only if rejected)
  A-->>B: result + trace
  B-->>F: description, price, trace
  F-->>U: AI panel (user reviews, then applies and saves)

  U->>F: Submit the form
  F->>B: POST /api/products
  B->>D: POST /products
  D-->>B: created row
  B-->>F: 201 Created
  F-->>U: alert + refreshed table (out-of-band HTMX swaps)
```

## 3. Docker Compose architecture

```mermaid
flowchart LR
  subgraph net["docker network: asd-net"]
    SH["shared-home<br/>nginx"]
    OLL["ollama"] --- OLI["ollama-init<br/>pulls the model, exits"]
    AMD["ai-mode"]
    DB1["student-1-db"]
    BE1["student-1-backend"]
    FE1["student-1-frontend"]
  end

  V1[("volume: ollama-data")] --- OLL
  V2[("volume: student-1-data")] --- DB1
  MNT[/"bind mount: ./shared (read-only)"/] --- FE1
  MNT --- SH

  FE1 --> BE1 --> DB1
  BE1 --> AMD --> OLL
```

Host ports: 3000 home · 3001/8001/9001 Student 1 · 7000 AI-Mode · 11434 Ollama.

## 4. Plan → Act → Observe → Adapt

```mermaid
flowchart LR
  P["Plan<br/>ground the prompt in<br/>database facts"] --> A["Act<br/>call the LLM through<br/>the Ollama runtime"]
  A --> O["Observe<br/>parse JSON, check<br/>schema + guardrails"]
  O -->|passes| R["Return result + trace<br/>to the user for review"]
  O -->|violations| AD["Adapt<br/>re-prompt with the<br/>exact violations"]
  AD --> A
  AD -->|retry budget spent| FB["Deterministic fallback<br/>supplied by the backend"]
  FB --> R
```

Implemented in `ai-services/ai-mode/agent/loop.py`; the caller's half (grounding, guardrails and
fallback) is in `student-1/backend/app/ai_agent.py`.

## 5. DevOps pipeline

```mermaid
flowchart LR
  DEV["Developer<br/>feature branch"] --> PR["Pull Request → main"]
  PR --> GA["GitHub Actions<br/>student-1.yml"]
  GA --> T["Lint + pytest<br/>(47 Student 1 tests, 10 AI-Mode tests)"]
  T --> BLD["docker build ×3<br/>+ docker compose config"]
  BLD --> SMK["Container smoke test<br/>real CRUD through the API"]
  SMK --> ART["Upload JUnit evidence"]
```
