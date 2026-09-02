# Scripts

Only commands that do more than wrap a single Docker call live here.

| Script | Purpose |
|---|---|
| `run-local.sh` | Create `.env` if missing, build and start the stack, follow the model pull, print every URL |
| `pull-model.sh` | Pull an approved LLM (defaults to `$LLM_MODEL`) into the running Ollama container |
| `run-tests.sh` | Run every implemented pytest suite and write JUnit evidence to `reports/` for the technical report |

Run them from Git Bash on Windows: `bash scripts/run-local.sh`.

Things that need no script:

```bash
docker compose up --build                          # start
docker compose down                                # stop  (-v also wipes the volumes)
docker compose logs -f student-1-backend           # tail one service
curl -X POST http://localhost:9001/admin/reseed    # reset Student 1's seed data
```
