#!/usr/bin/env bash
# Pull an approved open-source LLM into the running Ollama container.
#   ./scripts/pull-model.sh                # pulls $LLM_MODEL (default qwen2.5:0.5b)
#   ./scripts/pull-model.sh llama3.1:8b    # pulls a specific approved model
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:-${LLM_MODEL:-qwen2.5:0.5b}}"
echo "Pulling ${MODEL} into the Ollama runtime…"
docker compose exec -T ollama ollama pull "${MODEL}"
docker compose exec -T ollama ollama list
