# Scripts

Only commands that do more than wrap a single Docker call live here.

| Script | Purpose |
|---|---|
| `run-local.sh` | Create `.env` if missing, build and start the stack, follow the model pull, print every URL |
| `pull-model.sh` | Pull an approved LLM (defaults to `$LLM_MODEL`) into the running Ollama container |
| `run-tests.sh` | Run every implemented pytest suite and write JUnit evidence to `reports/` for the technical report |
| `run-ai-services.sh` | Start native AI-Mode (7001), genuine MCP Streamable HTTP (7002/mcp), and RAG (7003) |
| `run-multi-agent.sh` | Start only the native Multi-Agent workflow service (7004), preserving other running services |
| `aws/deploy.sh` | Build, push and deploy the whole group application to AWS (ECS Fargate), then validate it; needs `AWS_REGION` and `TF_STATE_BUCKET` |
| `aws/destroy.sh` | Remove the whole AWS deployment so it stops costing money (same two variables) |

Student 3 terminal workflow: `python scripts/multi-agent-workflow.py start --customer-id 1 --wait`, then use the printed workflow ID with `status` or `review`.

Student 1 terminal workflow: `python scripts/student-1-multi-agent.py start --product-id 1 --wait`, then `review --product-id 1 --workflow-id <id> --decision accept` (or `history --product-id 1`).

Run them from Git Bash on Windows: `bash scripts/run-local.sh`.

Things that need no script:

```bash
docker compose up --build                          # start
docker compose down                                # stop  (-v also wipes the volumes)
docker compose logs -f student-1-backend           # tail one service
curl -X POST http://localhost:9001/admin/reseed    # reset Student 1's seed data
```
