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

status=0
for requirement in "${requirements[@]}"; do
  if ! pip-audit --strict --requirement "${requirement}"; then
    status=1
  fi
done
exit "$status"
