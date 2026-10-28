#!/usr/bin/env bash
# Start only the shared native Multi-Agent service without restarting other services.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_DIR="$(pwd)"

if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in python3.11 python3 python; do
    if "${candidate}" -c 'import sys' >/dev/null 2>&1; then PYTHON_BIN=${candidate}; break; fi
  done
fi
"${PYTHON_BIN}" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

if [ -f .env ]; then
  for key in LLM_MODEL LLM_TIMEOUT MULTI_AGENT_PLANNER_MODEL MULTI_AGENT_WORKER_MODEL \
             MULTI_AGENT_REVIEWER_MODEL MULTI_AGENT_OLLAMA_URL MULTI_AGENT_STAGE_TIMEOUT \
             MULTI_AGENT_MAX_REVISIONS MULTI_AGENT_NUM_PREDICT; do
    if [ -z "${!key:-}" ]; then
      value=$(sed -n "s/^${key}=//p" .env | tr -d '\r' | tail -n 1)
      if [ -n "${value}" ]; then export "${key}=${value}"; fi
    fi
  done
fi

export MULTI_AGENT_OLLAMA_URL="${MULTI_AGENT_OLLAMA_URL:-http://127.0.0.1:11434}"
export LLM_MODEL="${LLM_MODEL:-qwen2.5:0.5b}"
export MULTI_AGENT_PLANNER_MODEL="${MULTI_AGENT_PLANNER_MODEL:-llama3.1:8b}"
export MULTI_AGENT_WORKER_MODEL="${MULTI_AGENT_WORKER_MODEL:-qwen2.5:3b}"
export MULTI_AGENT_REVIEWER_MODEL="${MULTI_AGENT_REVIEWER_MODEL:-llama3.1:8b}"
export SERVICE_PORT="${MULTI_AGENT_PORT:-7004}"

if curl -s -m 2 -o /dev/null "http://localhost:${SERVICE_PORT}/health"; then
  echo "A service is already answering on port ${SERVICE_PORT}. Use it as it is." >&2
  exit 1
fi

cd "${ROOT_DIR}/ai-services/multi-agent"
if [ ! -f .venv/Scripts/activate ] && [ ! -f .venv/bin/activate ]; then "${PYTHON_BIN}" -m venv .venv; fi
if [ -f .venv/Scripts/activate ]; then source .venv/Scripts/activate; else source .venv/bin/activate; fi
pip install -q -r requirements.txt
python server.py
