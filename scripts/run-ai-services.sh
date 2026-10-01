#!/usr/bin/env bash
# Start host AI-Mode, MCP and RAG services after Compose starts Ollama.
# Usage: bash scripts/run-ai-services.sh
# Stop: Ctrl+C stops all three services through the trap below.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_DIR="$(pwd)"

if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN=python3.11
  else
    PYTHON_BIN=python3
  fi
fi
"${PYTHON_BIN}" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export LLM_MODEL="${LLM_MODEL:-qwen2.5:0.5b}"

start_service() {
  local name=$1 dir=$2 port=$3 module=$4
  echo "Starting ${name} on :${port} ..."
  (
    cd "${ROOT_DIR}/${dir}"
    "${PYTHON_BIN}" -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
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
