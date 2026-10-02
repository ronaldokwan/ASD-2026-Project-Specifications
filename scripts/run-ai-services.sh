#!/usr/bin/env bash
# Start host AI-Mode, MCP and RAG services after Compose starts Ollama.
# Usage: bash scripts/run-ai-services.sh
# Stop: Ctrl+C stops all three services through the trap below.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_DIR="$(pwd)"

if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in python3.11 python3 python; do
    if "${candidate}" -c 'import sys' >/dev/null 2>&1; then
      PYTHON_BIN=${candidate}
      break
    fi
  done
fi
"${PYTHON_BIN}" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

# Use the same model settings as Compose, otherwise these services ask Ollama
# for a model it never pulled. Only host-safe keys are read: the *_URL entries
# in .env are container addresses (ollama, host.docker.internal). Exported
# values win.
if [ -f .env ]; then
  for key in LLM_MODEL LLM_TIMEOUT; do
    if [ -z "${!key:-}" ]; then
      value=$(sed -n "s/^${key}=//p" .env | tr -d '\r' | tail -n 1)
      if [ -n "${value}" ]; then export "${key}=${value}"; fi
    fi
  done
fi

export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export LLM_MODEL="${LLM_MODEL:-qwen2.5:3b}"

# Refuse to start a second copy: on Windows a running service also locks its
# venv's python.exe, so recreating the venv would fail with "Permission denied".
busy=""
for port in 7001 7002 7003; do
  if curl -s -m 2 -o /dev/null "http://localhost:${port}/health"; then
    busy="${busy} ${port}"
  fi
done
if [ -n "${busy}" ]; then
  echo "Already running on port(s)${busy}. Stop the existing services first," >&2
  echo "or use them as they are (check http://localhost:7001/health)." >&2
  exit 1
fi

start_service() {
  local name=$1 dir=$2 port=$3 module=$4
  echo "Starting ${name} on :${port} ..."
  (
    cd "${ROOT_DIR}/${dir}"
    # Reuse an existing venv; only create one on the first run.
    if [ ! -f .venv/Scripts/activate ] && [ ! -f .venv/bin/activate ]; then
      "${PYTHON_BIN}" -m venv .venv
    fi
    # shellcheck disable=SC1091
    if [ -f .venv/Scripts/activate ]; then
      source .venv/Scripts/activate   # Windows venv layout
    else
      source .venv/bin/activate
    fi
    pip install -q -r requirements.txt
    SERVICE_PORT="${port}" python "${module}"
  ) &
}

start_service "AI-Mode"           ai-services/ai-mode    7001 app.py
start_service "shared MCP server" ai-services/mcp-server 7002 server.py
start_service "shared RAG server" ai-services/rag-server 7003 http_server.py

trap 'echo; echo "Stopping..."; kill 0' INT TERM

echo
echo "AI-Mode      http://localhost:7001/health"
echo "MCP server   http://localhost:7002/mcp  (health: /health)"
echo "RAG server   http://localhost:7003/health"
echo
echo "Press Ctrl+C to stop all three."
wait
