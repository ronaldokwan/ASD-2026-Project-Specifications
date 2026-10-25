# Student 1 – Release 2 screenshots

File names start with the marking criterion they support (`c1` = criterion 1, …).
Captured 22–23 Oct 2026 on the Student 1 laptop, branch `ronaldo`.

**How they were made**
- *Browser*: the running local app (`http://localhost:3001`) or the public GitHub page, captured
  with headless Microsoft Edge. Each local capture carries a caption bar with its URL and time.
- *Terminal*: real command output captured on the laptop (or fetched from GitHub with `gh`),
  rendered as an image. The `$` line is the exact command that produced the output.

| File | Criterion | Shows | How |
|---|---|---|---|
| `c1-01-catalogue-overview.png` | 1 Local app | Whole Product Catalogue page: form, AI, MCP, RAG and Multi-Agent cards, product table | Browser |
| `c1-02-create-product.png` | 1 CRUD – create | "Created …" alert and the new product at the top of the table | Browser |
| `c1-03-update-product.png` | 1 CRUD – update | "Updated …" alert after changing the price | Browser |
| `c1-04-delete-product.png` | 1 CRUD – delete | "Product #… deleted" alert | Browser |
| `c1-05-ai-mode-suggestion.png` | 1 AI-Mode (R0) | Generated description + price with the Plan → Act → Observe trace | Browser |
| `c1-06-mcp-listing-check.png` | 1 MCP (R1) | `check_product_listing` result for the Aurora Desk Lamp | Browser |
| `c1-07-rag-grounded-answer.png` | 1 RAG (R1) | Grounded answer with confidence and cited source | Browser |
| `c1-08-multi-server-local.png` | 1 Local deployment | Docker Compose containers + native AI services 7001–7004 + backend health | Terminal |
| `c2-01-multi-agent-started.png` | 2 Multi-Agent (UI) | Review started, Planner stage running | Browser |
| `c2-02-planner-worker-reviewer.png` | 2 | Completed Planner, Worker, Reviewer, application cross-check, human-review form | Browser |
| `c2-03-human-review-decision.png` | 2 Human review | Recorded **accept** decision and workflow history | Browser |
| `c2-04-workflow-history.png` | 2 History | Per-product workflow history with the viewed run marked | Browser |
| `c2-05-multi-agent-terminal-cli.png` | 2 Multi-Agent (terminal) | `student-1-multi-agent.py` start → stages → human review → **accept** (Reviewer raised a false alarm; the human decision explains why it was overruled) | Terminal |
| `c2-escalation-01…04-*.png` | 2 Robustness | A run where the Reviewer contradicted itself 3 times: escalated to Human Review flagged *unchecked* instead of failing | Browser |
| `c3-01-pre-commit-security-scans.png` | 3 Pre-commit | Ruff security, detect-secrets, pip-audit all **Passed** (exit code 0) | Terminal |
| `c4-01-github-run-success.png` | 4 Post-commit CI | `student-1.yml` run #77 (39799057050): Success, both jobs, 2 evidence artifacts | Browser (github.com) |
| `c4-02-post-commit-endpoint-tests-ci-log.png` | 4 | CI step 9: 10 endpoint tests of `create_product` and `update_product` **PASSED** | Terminal (`gh run view --log`) |
| `c4-03-ci-security-scans-log.png` | 3 / 4 | CI step 5: the same three security hooks **Passed** in GitHub Actions | Terminal (`gh run view --log`) |
| `c8-01-testing-review-passed.png` | 8 Testing Review | Agentic-loop review of the CI evidence: **passed**, with validation log | Terminal |
| `c8-02-multi-agent-review-supported.png` | 8 Multi-Agent Review | Review of an accepted workflow: **supported** | Terminal |
| `c8-03-multi-agent-review-issues-found.png` | 8 Multi-Agent Review | Review of a rejected workflow: **issues_found** | Terminal |
| `c8-04-cloud-deployment-review-ready.png` | 8 Cloud Deployment Review | Review of the live AWS deployment: **ready** (gate and model agree) | Terminal |
| `c5-01-aws-build-push-and-terraform-apply.png` | 5 Deployment scripts | `build-push-images.sh` published all images; Terraform `Apply complete!` with the public URLs | Terminal |
| `c5-02-aws-ecr-images.png` | 5 | All 16 group images in Amazon ECR with the deployed tag | Terminal (AWS CLI) |
| `c7-01-cloud-home-page.png` | 7 Cloud app | Group home page on the AWS load balancer | Browser (AWS) |
| `c7-02-cloud-catalogue.png` | 7 | Product Catalogue on AWS (`:3001`) | Browser (AWS) |
| `c7-03-cloud-create-product.png` | 7 Cloud CRUD – create | "Created …" on AWS | Browser (AWS) |
| `c7-04-cloud-update-product.png` | 7 Cloud CRUD – update | "Updated …" on AWS | Browser (AWS) |
| `c7-05-cloud-delete-product.png` | 7 Cloud CRUD – delete | "… deleted" on AWS | Browser (AWS) |
| `c7-06-cloud-mcp-disabled.png` | 7 AI disabled | MCP check answers "MCP integration is disabled" in the cloud | Browser (AWS) |
| `c7-07-cloud-multi-agent-disabled.png` | 7 AI disabled | Multi-Agent review unavailable in the cloud | Browser (AWS) |
| `c7-08-cloud-health-ai-disabled.png` | 7 AI disabled | `/health`: database ok; AI-Mode, MCP, RAG, Multi-Agent all `disabled` | Browser (AWS) |
| `c7-09-aws-ecs-services-running.png` | 7 | ECS Fargate: 16/16 services running, rollout COMPLETED | Terminal (AWS CLI) |
| `c7-10-aws-runtime-validation.png` | 5 / 7 | `validate-runtime.sh`: home, 5 frontends, Student 1 + 3 CRUD, AI disabled (exit 0) | Terminal |
| `bonus-b5-cloud-endpoint-security.png` | Bonus B5 | Only ports 80/3001–3005 public; backend 8001 and database 9001 refuse connections; tasks have no public IP | Terminal (AWS CLI) |
| `bonus-b6-cloud-data-security.png` | Bonus B6 | EFS databases encrypted; state bucket AES256, public access blocked, versioned, TLS-only; ECR AES256 + immutable tags | Terminal (AWS CLI) |

**Notes**
- GitHub hides step logs from signed-out visitors, so the CI step logs (`c4-02`, `c4-03`) were
  fetched with the authenticated GitHub CLI and rendered; `c4-01` is the public run page.
- The human-review decisions in these captures were recorded during the automated capture. For
  the showcase video, record a decision yourself in the UI.
- AWS: account 604707013588, region `ap-southeast-2`, image tag `r2-202610230339`, captured
  23 Oct 2026. Raw evidence: `../aws/` (validation JSON, Terraform outputs) and `../cloud-review/`.
- Deployment defects found and fixed before these captures: ECS service registries sent
  `containerPort` for A records (every database service was rejected); the load-balancer
  security-group rules were defined twice and removed by each apply (and the home page had none);
  cloud frontend images lacked the team `shared/` theme (unstyled pages); the validator did not
  follow Student 2's `/ → /orders` redirect.
- Not yet captured: `cloud-deployment.yml` running in GitHub Actions (criterion 6), which needs the
  work merged to `main` and an AWS role for GitHub.
