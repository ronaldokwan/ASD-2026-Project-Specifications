#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

requirements=(
  student-1/backend/requirements.txt
  student-1/frontend/requirements.txt
  student-1/database/requirements.txt
  student-3/backend/requirements.txt
  student-3/frontend/requirements.txt
  student-3/database/requirements.txt
  ai-services/ai-mode/requirements.txt
  ai-services/mcp-server/requirements.txt
  ai-services/rag-server/requirements.txt
  ai-services/multi-agent/requirements.txt
  student-4/backend/requirements.txt
  student-4/frontend/requirements.txt
  student-4/database/requirements.txt
  student-5/backend/requirements.txt
  student-5/frontend/requirements.txt
  student-5/database/requirements.txt
)

# Documented accepted risk, by advisory ID only so any new finding still fails:
# chromadb 1.5.9 has no fixed release for these advisories. It backs only the
# local, non-containerised RAG server, which is disabled and not deployed in
# the cloud baseline. Remove an ID as soon as a fixed chromadb is released.
accepted=(PYSEC-2026-311 PYSEC-2026-3813 PYSEC-2026-3814 PYSEC-2026-3815)
ignore_args=()
for id in "${accepted[@]}"; do ignore_args+=(--ignore-vuln "$id"); done

status=0
for requirement in "${requirements[@]}"; do
  if ! pip-audit --strict "${ignore_args[@]}" --requirement "${requirement}"; then
    status=1
  fi
done
exit "$status"
