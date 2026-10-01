#!/usr/bin/env bash
# Build and start the whole integrated application locally (Docker Compose).
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Creating .env from .env.example"; cp .env.example .env; }

docker compose up --build -d
echo
echo "Waiting for the model to be pulled (first run only)…"
docker compose logs -f ollama-init 2>/dev/null || true

echo
echo "Integrated application:"
echo "  home page          http://localhost:3000"
echo "  product catalogue  http://localhost:3001   (Student 1 - Ronaldo Kwan)"
echo "  catalogue API      http://localhost:8001/api/products"
echo
echo "AI-Mode, the shared MCP server and the shared RAG server are not part of"
echo "this stack (Release 1: they run natively) - start them separately with:"
echo "  bash scripts/run-ai-services.sh"
docker compose ps
