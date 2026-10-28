# group-40 – Release 2 Technical Report

ASD 2026 · Assessment 3 – Release 2: Multi-Agent Systems, Testing & Cloud Deployment · Canvas Group 40

GitHub repository: [github.com/ronaldokwan/ASD-2026-Project-Specifications](https://github.com/ronaldokwan/ASD-2026-Project-Specifications)

Showcase video: [https://www.youtube.com/watch?v=aBeqeT3EuwE](https://www.youtube.com/watch?v=aBeqeT3EuwE)

## 1. Project Overview

| # | Student | Feature | Microservices (frontend / backend / database) |
|---|---|---|---|
| 1 | Ronaldo Kwan (team leader) | Product Catalogue | 3001 / 8001 / 9001 |
| 2 | Jinying Li | Customer Orders | 3002 / 8002 / 9002 |
| 3 | Vishvak Ananthakrishnan Rameshkumar | Customer Account Management | 3003 / 8003 / 9003 |
| 4 | Jonathan Czesler | Inventory and Stock | 3004 / 8004 / 9004 |
| 5 | Alexander McGuinn | Reviews and Ratings | 3005 / 8005 / 9005 |

SmartShop is an Agentic AI retail application built as microservices. Each of the five features has its own frontend, backend/API and SQLite database microservice; locally they run under Docker Compose, in the cloud on AWS ECS Fargate. Release 0 added the shared AI-Mode agentic loop (Plan → Act → Observe) and Release 1 the shared MCP and RAG servers, all native host services. Release 2 extends the completed Release 1 application with:

| Release 2 addition | Where |
|---|---|
| Shared Multi-Agent Server: Planner → Worker → Reviewer with a Human Review gate, workflow history and a coordination audit log; callable from the backends and the terminal | `ai-services/multi-agent/` (native, port 7004) |
| Agentic-loop review modes Multi-Agent Workflow, Testing Report and Cloud Deployment Report, alongside the Release 1 MCP and RAG modes; each pairs a deterministic evidence gate with the model review and saves a validation log | `ai-services/ai-mode/agent/review_modes.py` |
| Local pre-commit security scans and post-commit endpoint tests | `.pre-commit-config.yaml`, `student-x.yml` |
| AWS deployment: Terraform, reusable scripts and a gated deployment workflow, with AI services disabled by default | `infra/aws/`, `scripts/aws/`, `cloud-deployment.yml` |

## 2. Final Repository Structure

Release 2 additions are marked **R2**.

```
ASD-2026-Project-Specifications/
├── .github/workflows/       student-1.yml … student-5.yml · cloud-deployment.yml (R2)
├── .pre-commit-config.yaml  Ruff security, detect-secrets, pip-audit hooks (R2)
├── docker-compose.yml       frontends, backends, databases, shared home, Ollama
├── ai-services/             native host services, not in Docker Compose
│   ├── ai-mode/             R0 agentic loop · R1 MCP/RAG validation · R2 review modes
│   ├── mcp-server/          R1 MCP server (Streamable HTTP, :7002/mcp)
│   ├── rag-server/          R1 RAG server (:7003)
│   └── multi-agent/         R2 Planner → Worker → Reviewer → Human Review (:7004)
├── student-1/ … student-5/  frontend, backend/API, database and tests per student
├── shared/                  team home page, theme and service config
├── infra/aws/               R2 Terraform: VPC, ALB, ECS Fargate, ECR, EFS, Cloud Map
│   └── github-oidc/         R2 GitHub OIDC deploy role
├── scripts/                 run-local, run-ai-services, run-multi-agent, run-tests
│   ├── aws/                 R2 bootstrap-state, init, build-push-images, deploy,
│   │                        validate-runtime, destroy, setup-github-oidc
│   └── security/            R2 pip-audit hook
└── docs/                    architecture, diagrams/, evidence/ (R2 logs), reports/
```

## 3. Release 2 Design Flow

### 3.1 Student 1 – Ronaldo Kwan – Product Catalogue

![Student 1 Release 2 design flow: Frontend UI → Backend/API → Database, the Release 0/1 AI-Mode, MCP and RAG calls, and Multi-Agent Server → Planner → Worker → Reviewer → Human Review → response to the Frontend UI.](docs/diagrams/student-1-release-2-design-flow.png)

For a listing-readiness review the backend sends the Multi-Agent Server three evidence items: `product_facts` (stored fields plus the application's deterministic check of each *Listing Readiness* rule), the MCP `check_product_listing` result and the RAG catalogue policy. Missing MCP or RAG evidence is sent as `unavailable`, which forces the Reviewer to `not_supported`. The human decision is advisory: a product only changes through the catalogue form.

### 3.2 Student 2 – Jinying Li – Customer Orders

> TODO (Student 2): Updated design flow including the Multi-Agent flow.

### 3.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar – Customer Account Management

> TODO (Student 3): Updated design flow including the Multi-Agent flow.

### 3.4 Student 4 – Jonathan Czesler – Inventory and Stock

> TODO (Student 4): Updated design flow including the Multi-Agent flow.

### 3.5 Student 5 – Alexander McGuinn – Reviews and Ratings

> TODO (Student 5): Updated design flow including the Multi-Agent flow.

## 4. Cloud Deployment and CI/CD Architecture

The group selected **AWS**. An internet-facing Application Load Balancer in two public subnets exposes only the home page (:80) and the five frontends (:3001–:3005). All 16 services run as ECS Fargate tasks in private subnets with no public IP and no NAT gateway; frontends reach backends and backends reach databases through Cloud Map private DNS. Each SQLite database runs as a single task on an encrypted EFS access point. Images come from ECR and logs go to CloudWatch through VPC endpoints. AI-Mode, MCP, RAG and Multi-Agent are disabled by default.

![AWS reference architecture of the integrated group application (infra/aws/main.tf).](docs/diagrams/aws-reference-architecture.png)

Infrastructure is Terraform (`infra/aws/`, remote state in S3 with locking); `scripts/aws/` makes the deployment reusable and non-interactive: `bootstrap-state.sh`, `init.sh`, `build-push-images.sh`, `deploy.sh`, `validate-runtime.sh` and `destroy.sh`. `cloud-deployment.yml` deploys only after its `required-ci` job passes (security hooks, every student's tests, Terraform and Compose validation, all 16 image builds) and authenticates through a GitHub OIDC role, so no AWS keys are stored in GitHub.

![DevOps flow: source control → pre-commit security scans → GitHub Actions → post-commit endpoint tests → Docker build/validation → cloud-deployment.yml → AWS.](docs/diagrams/devops-pipeline.png)

## 5. Pre-Commit Security Testing

The shared `.pre-commit-config.yaml` is installed with `pre-commit install`, so it runs on every `git commit` and blocks the commit on failure. `cloud-deployment.yml` runs the same hooks over all files before any deployment.

| Hook | Version | Scope |
|---|---|---|
| Ruff security rules (`--select S`) | ruff 0.12.10 | Python in `ai-services/`, `scripts/` and the Python student services listed in the config |
| detect-secrets | 1.5.0 | every staged file except `.env`, databases and logs |
| pip-audit `--strict` | 2.9.0 | 16 Python requirement files (`scripts/security/pip-audit.sh`); Student 2's Java services are built with Maven |

### 5.1 Student 1 – Ronaldo Kwan

Hook run over all tracked files on 23 Oct 2026, exit code 0 (`docs/evidence/student-1/release-2/01-pre-commit-security-scans.log`); `student-1.yml` re-runs it on every push.

| Hook | Scope | Result |
|---|---|---|
| Ruff security (`--select S`) | all Python in `student-1/`, `ai-services/`, `scripts/` | **Passed** |
| detect-secrets | every tracked file except `.env`, databases, logs | **Passed** |
| pip-audit `--strict` | 16 requirement files | **Passed** (4 documented exceptions) |

Findings resolved: S201 `debug=True` removed from the three Student 1 services and the MCP HTTP server; S104 (`0.0.0.0`) accepted per file for the native MCP/RAG servers, which containers reach through `host.docker.internal`. Accepted risk: `chromadb 1.5.9` has four advisories with no fixed release; it backs only the local RAG server, not the cloud baseline, and is ignored by ID so any new advisory still fails the commit.

![Pre-commit hook run: Ruff security rules, detect-secrets and pip-audit all Passed.](docs/evidence/student-1/release-2/screenshots/c3-01-pre-commit-security-scans.png)

![The same three security hooks passing in GitHub Actions (student-1.yml).](docs/evidence/student-1/release-2/screenshots/c4-03-ci-security-scans-log.png)

### 5.2 Student 2 – Jinying Li

Student 2 executed the shared pre-commit configuration over all tracked files on 27 Oct 2026 at commit `1d0d0a2`; the command exited successfully and the Git hook was installed for subsequent commits. Ruff security rules, detect-secrets and pip-audit all passed. Ruff and pip-audit cover the shared Python AI services and Python dependencies, while Student 2's Customer Orders services are Java/Maven; detect-secrets covers Student 2 source, workflow and configuration files. The strict pip-audit run retained only the four documented ChromaDB advisory exceptions that currently have no fixed release, and found no additional blocking vulnerability. Evidence: `docs/evidence/student-2/release-2/01-pre-commit-security-scans.log`.

| Hook | Student 2 / shared scope | Result |
|---|---|---|
| Ruff security (`--select S`) | Shared Python AI services, scripts and configured Python services; Student 2 contains no Python source | **Passed** |
| detect-secrets | All covered tracked files, including Student 2 source, workflow and configuration | **Passed** |
| pip-audit `--strict` | 16 shared Python requirement files; Java dependencies are validated by Maven | **Passed** (4 documented ChromaDB exceptions) |

### 5.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Pre-commit security testing report.

### 5.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Pre-commit security testing report.

### 5.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Pre-commit security testing report.

## 6. Post-Commit CI/CD Testing

### 6.1 Student 1 – Ronaldo Kwan (`student-1.yml`)

Pipeline: security scans → lint → 149 unit/integration tests → shared AI service tests → Docker build → Compose up → **endpoint tests against the live container** → CRUD and frontend smoke tests → AI services disabled check.

| Endpoint function | Route | Tests | Asserted |
|---|---|---|---|
| `create_product` | `POST /api/products` | 6 | 201 with normalised, persisted record; SKU generated when omitted; 400 for bad category, price or missing name; 409 duplicate SKU |
| `update_product` | `PUT /api/products/<id>` | 4 | partial update persists only supplied fields; invalid price 400 with record unchanged; empty body 400; unknown id 404 |

Hosted run [39799057050](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/actions/runs/39799057050) (22 Oct 2026, commit `8241b55`): **success**, 10/10 endpoint tests passed, 149 microservice tests passed, security hooks 3/3 passed. Artifacts: `docs/evidence/student-1/release-2/ci-run-39799057050/`.

![student-1.yml run 39799057050: success, both jobs, evidence artifacts uploaded.](docs/evidence/student-1/release-2/screenshots/c4-01-github-run-success.png)

![student-1.yml CI log: the 10 post-commit endpoint tests of create_product and update_product passed against the live container.](docs/reports/figures/student-1/c4-02-post-commit-endpoint-tests-ci-log.png)

### 6.2 Student 2 – Jinying Li (`student-2.yml`)

> TODO (Student 2): Post-commit tests of two backend/API endpoint functions and workflow evidence.

### 6.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar (`student-3.yml`)

> TODO (Student 3): Post-commit tests of two backend/API endpoint functions and workflow evidence.

### 6.4 Student 4 – Jonathan Czesler (`student-4.yml`)

> TODO (Student 4): Post-commit tests of two backend/API endpoint functions and workflow evidence.

### 6.5 Student 5 – Alexander McGuinn (`student-5.yml`)

> TODO (Student 5): Post-commit tests of two backend/API endpoint functions and workflow evidence.

## 7. Testing Review

### 7.1 Student 1 – Ronaldo Kwan

The agentic-loop Testing Review mode (`llama3.1:8b`) was run on local and hosted evidence:

| Input | Gate | Model | Result | Evidence |
|---|---|---|---|---|
| Local hook log and endpoint run, GitHub Actions not run | incomplete | incomplete | **incomplete** | `testing-review-local/` |
| CI run 39799057050: hook log and endpoint JUnit, CI passed | passed | passed | **passed** | `testing-review-ci/` |

The validation log records *"All three pre-commit security hooks and at least two post-commit backend endpoint tests passed"*, with gate and model in agreement.

![Agentic-loop Testing Review of the hosted CI evidence: passed, with its validation log.](docs/evidence/student-1/release-2/screenshots/c8-01-testing-review-passed.png)

### 7.2 Student 2 – Jinying Li

> TODO (Student 2): Testing Review output and validation log.

### 7.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Testing Review output and validation log.

### 7.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Testing Review output and validation log.

### 7.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Testing Review output and validation log.

## 8. Local Deployment Evidence

`docker compose up --build` starts the shared home page, Ollama and all fifteen student microservices. AI-Mode (7001), MCP (7002), RAG (7003) and the Multi-Agent Server (7004) are not Compose services: `bash scripts/run-ai-services.sh` starts them natively in a second terminal, and backends reach them through `host.docker.internal`. A third terminal runs the checks.

> TODO (group): Multi-terminal log of the integrated run for all five students.

### 8.1 Student 1 – Ronaldo Kwan

The three Student 1 containers run under Docker Compose (`MULTI_AGENT_URL=host.docker.internal:7004`); AI-Mode, MCP, RAG and Multi-Agent run natively.

| Terminal | Command | Role |
|---|---|---|
| 1 | `docker compose up --build` | containerised microservices |
| 2 | `bash scripts/run-ai-services.sh` | native AI-Mode 7001, MCP 7002, RAG 7003, Multi-Agent 7004 |
| 3 | `bash scripts/multi-server-check.sh` | probes every service and Student 1's paths to the database, MCP, RAG and Multi-Agent; writes `05-multi-server-check.log` |

![Local multi-server view: Compose containers, native AI services on 7001–7004 and backend health.](docs/evidence/student-1/release-2/screenshots/c1-08-multi-server-local.png)

![Local CRUD through the Student 1 frontend: create, update and delete.](docs/reports/figures/student-1/c1-crud-local.png)

![Release 0/1 services retained locally: AI-Mode suggestion with its Plan → Act → Observe trace, MCP listing check, grounded RAG answer.](docs/reports/figures/student-1/c1-ai-mcp-rag-local.png)

### 8.2 Student 2 – Jinying Li

> TODO (Student 2): Local deployment evidence.

### 8.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Local deployment evidence.

### 8.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Local deployment evidence.

### 8.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Local deployment evidence.

## 9. Cloud Deployment Report and Review

The integrated application was deployed on 23 Oct 2026 with `scripts/aws/deploy.sh` (image tag `r2-202610230339`): all 16 images were pushed to ECR, Terraform created the stack and ECS reported 16/16 services running. `validate-runtime.sh` passed: home page and all five frontends returned HTTP 200, Student 1 and Student 3 CRUD were verified through their public frontends and private databases, and the AI services reported disabled. The agentic-loop Cloud Deployment Review assessed the deployment as **ready**. The stack was then removed with `destroy.sh`. Evidence: `docs/evidence/student-1/release-2/aws/` and `cloud-review/`.

**Final human release decision: approve release.** The group approves the AWS release on the evidence above: the integrated application and CRUD work in the cloud, AI-Mode, MCP, RAG and Multi-Agent stay disabled by default, and both the runtime validation and the Cloud Deployment Review report it ready.

> TODO (group): `cloud-deployment.yml` GitHub Actions run log. The OIDC deploy role and the `aws-production` environment are now set up. Run 40342920579 (26 Oct) passed the security hooks, all tests and infrastructure validation, then failed building Student 2's images (Dockerfile paths); the deploy job was skipped. Push the path fix and re-run.

### 9.1 Student 1 – Ronaldo Kwan

Deployed on 23 Oct 2026 with `scripts/aws/deploy.sh` (`ap-southeast-2`, image tag `r2-202610230339`); `validate-runtime.sh` passed (`docs/evidence/student-1/release-2/aws/`).

| Check | Result |
|---|---|
| Home page and frontends `:3001`–`:3005` | HTTP 200 |
| Student 1 CRUD: public frontend → private backend → EFS database | create, update, delete, list verified |
| Student 1 AI-Mode, MCP, RAG, Multi-Agent | all `disabled` (cloud baseline) |

A first deploy failed validation and exposed four defects, fixed before the successful run: service-registry ports, duplicated load-balancer security-group rules, cloud frontends missing the shared theme, and the validator not following Student 2's redirect. The agentic-loop Cloud Deployment Review of the live deployment returned **ready**, with gate and model in agreement (`cloud-review/`).

![Deployment scripts: build-push-images.sh published every image; Terraform apply complete with the public URLs.](docs/evidence/student-1/release-2/screenshots/c5-01-aws-build-push-and-terraform-apply.png)

![All 16 group images in Amazon ECR with the deployed tag.](docs/evidence/student-1/release-2/screenshots/c5-02-aws-ecr-images.png)

![Group home page on the AWS load balancer.](docs/evidence/student-1/release-2/screenshots/c7-01-cloud-home-page.png)

![Cloud CRUD through the Student 1 AWS frontend: create, update and delete.](docs/reports/figures/student-1/c7-crud-cloud.png)

![AWS frontend: MCP check and Multi-Agent review unavailable, as the AI services are not deployed in the cloud baseline.](docs/reports/figures/student-1/c7-06-07-cloud-ai-disabled.png)

![ECS Fargate: 16/16 services running, rollout completed.](docs/evidence/student-1/release-2/screenshots/c7-09-aws-ecs-services-running.png)

![validate-runtime.sh: home page, five frontends, Student 1 and 3 CRUD, AI services disabled (exit 0).](docs/evidence/student-1/release-2/screenshots/c7-10-aws-runtime-validation.png)

![Agentic-loop Cloud Deployment Review of the live AWS deployment: ready.](docs/evidence/student-1/release-2/screenshots/c8-04-cloud-deployment-review-ready.png)

### 9.2 Student 2 – Jinying Li

> TODO (Student 2): Cloud deployment evidence for Customer Orders.

### 9.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Cloud deployment evidence for Customer Account Management.

### 9.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Cloud deployment evidence for Inventory and Stock.

### 9.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Cloud deployment evidence for Reviews and Ratings.

## 10. Multi-Agent Workflow Evidence

### 10.1 Student 1 – Ronaldo Kwan

The first live runs failed: the Worker (`qwen2.5:3b`) miscounted rule checks, and the Reviewer (`deepseek-r1:8b`) caught the error but marked every claim supported, so the shared server rejected the whole workflow. The fix moved rule arithmetic into the application (`readiness_checks`, `failed_checks`), added retries with escalation to Human Review, and switched the Reviewer to `llama3.1:8b`, which caught 3 of 4 wrong answers in a replay test with no wrong verdicts. An application cross-check of the Worker's verdict is shown beside the Reviewer at Human Review.

| Run | Product | Worker | Reviewer | Cross-check | Human decision | Multi-Agent Review |
|---|---|---|---|---|---|---|
| Terminal | #2 Pebble Bluetooth Speaker | ready (correct) | claims supported | agrees | **accept** | supported |
| Frontend UI | #7 Dual Port USB-C Charger (draft) | ready (wrong) | rationale unsupported | **disagrees** | **reject** | issues_found |

Each run's workflow history (`multi-agent-workflow.json`) and coordination audit log (`coordination-audit-log.jsonl`, 9 events from `workflow_created` to `human_decision_recorded`) are in `docs/evidence/student-1/release-2/multi-agent-terminal-run/` and `multi-agent-ui-run/`.

![Frontend UI: Planner, Worker and Reviewer stages, application cross-check and the Human Review form.](docs/reports/figures/student-1/c2-02-planner-worker-reviewer.png)

![Frontend UI: Human Review decision recorded, with the per-product workflow history.](docs/reports/figures/student-1/c2-03-human-review-decision.png)

![Terminal: student-1-multi-agent.py start → Planner → Worker → Reviewer → Human Review decision.](docs/evidence/student-1/release-2/screenshots/c2-05-multi-agent-terminal-cli.png)

![Agentic-loop Multi-Agent Review of the accepted terminal run: supported.](docs/evidence/student-1/release-2/screenshots/c8-02-multi-agent-review-supported.png)

![Agentic-loop Multi-Agent Review of the rejected UI run: issues_found, with its validation log.](docs/evidence/student-1/release-2/screenshots/c8-03-multi-agent-review-issues-found.png)

![Robustness: a Reviewer that contradicted itself three times was escalated to Human Review flagged unchecked instead of failing the workflow.](docs/reports/figures/student-1/c2-escalation-03-human-review-decision.png)

### 10.2 Student 2 – Jinying Li

> TODO (Student 2): Planner → Worker → Reviewer → Human Review run, workflow history and audit log.

### 10.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Planner → Worker → Reviewer → Human Review run, workflow history and audit log.

### 10.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Planner → Worker → Reviewer → Human Review run, workflow history and audit log.

### 10.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Planner → Worker → Reviewer → Human Review run, workflow history and audit log.

## 11. GitHub Commit Logs

Commit history: [github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main)

| Student | Release 2 commits |
|---|---|
| 1 – Ronaldo Kwan | [ronaldokwan](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=ronaldokwan) |
| 2 – Jinying Li | [JYL701](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=JYL701), [XanonymXX](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=XanonymXX) |
| 3 – Vishvak Ananthakrishnan Rameshkumar | [vishvak8](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=vishvak8), [Vish7A](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=Vish7A) |
| 4 – Jonathan Czesler | [Jono-Cz](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=Jono-Cz) |
| 5 – Alexander McGuinn | [AlexMcGuinn](https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=AlexMcGuinn) |

## 12. Contribution Logs

### 12.1 Student 1 – Ronaldo Kwan

| Date | Work |
|---|---|
| 22 Oct 2026 | Multi-Agent client, routes, UI panel with history and Human Review, terminal CLI; 38 new tests and 10 post-commit endpoint tests; `student-1.yml` Release 2 pipeline; pre-commit coverage for Student 1 and shared Ruff fixes |
| 23 Oct 2026 | Diagnosed live Reviewer failures; deterministic readiness checks, application cross-check, shared-server retry and Human Review escalation; Reviewer model evaluation; terminal and UI Multi-Agent runs; Testing and Multi-Agent reviews |
| 23 Oct 2026 | AWS deployment of the group application, four deployment defects fixed, runtime validation, Cloud Deployment Review, cloud and bonus evidence, teardown |
| 27 Oct 2026 | GitHub OIDC deploy role (`infra/aws/github-oidc/`) and `cloud-deployment.yml` fixes for the hosted deploy; multi-server check script; evidence logs |

### 12.2 Student 2 – Jinying Li

| Date | Work |
|---|---|
| 22 Oct 2026 | Extended `student-2.yml` with post-commit tests for live order retrieval and status updates, including the HTTP 400 validation case and uploaded test evidence. |
| 23 Oct 2026 | Integrated Customer Orders with the shared Multi-Agent Server. Added the Planner, Worker and Reviewer workflow, sanitised order/MCP/RAG evidence, Human Review decisions and per-order workflow history in the frontend. |
| 27 Oct 2026 | Ran the shared Ruff, detect-secrets and pip-audit checks; validated the local Student 2 containers and native AI services; collected local and AWS Customer Orders CRUD evidence. |
| 28 Oct 2026 | Added the completion-gate integration and Human Review UI fix, expanded backend/frontend tests, generated Testing Review and Multi-Agent Workflow Review evidence, and verified the full Student 2 Maven build. |

### 12.3 Student 3 – Vishvak Ananthakrishnan Rameshkumar

> TODO (Student 3): Release 2 contribution record.

### 12.4 Student 4 – Jonathan Czesler

> TODO (Student 4): Release 2 contribution record.

### 12.5 Student 5 – Alexander McGuinn

> TODO (Student 5): Release 2 contribution record.

## 13. Bonus Evidence

Claimed: **B5 Cloud Endpoint Security** and **B6 Cloud Data Security**. B1–B4 (AI services in the cloud) are not claimed; the cloud deployment keeps them disabled.

| Bonus | Controls (`infra/aws/main.tf`) | Validation |
|---|---|---|
| B5 Endpoint security | ALB security group admits only :80 and :3001–:3005; tasks run in private subnets without public IPs; the tasks security group accepts traffic only from the ALB and other application tasks | backend :8001 and database :9001 refuse connections from the internet; ECS reports no public IP (B5 screenshot below) |
| B6 Data security | EFS encrypted at rest, TLS in transit, IAM-authorised access point per database; S3 state bucket AES256, versioned, TLS-only, public access blocked; ECR AES256 with immutable tags; GitHub OIDC role instead of stored AWS keys | AWS CLI queries of EFS, S3 and ECR settings (B6 screenshot below) |

![B5 endpoint security: only ports 80 and 3001–3005 are public; backend and database ports refuse connections; tasks have no public IP.](docs/evidence/student-1/release-2/screenshots/bonus-b5-cloud-endpoint-security.png)

![B6 data security: encrypted EFS, encrypted TLS-only state bucket, ECR AES256 with immutable tags.](docs/evidence/student-1/release-2/screenshots/bonus-b6-cloud-data-security.png)

## 14. Showcase Video URL

[https://www.youtube.com/watch?v=aBeqeT3EuwE](https://www.youtube.com/watch?v=aBeqeT3EuwE)
