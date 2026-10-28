#!/usr/bin/env bash
# Bonus cloud AI profile check (B1-B4): drives AI-Mode, MCP, RAG and the Multi-Agent
# workflow through the public Student 1 frontend -> private backend -> ai-services task,
# and saves every response under $OUT for the report.
# Usage: APP_BASE_URL=http://<alb-dns> bash scripts/aws/validate-cloud-ai.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
url="${APP_BASE_URL:-$(terraform -chdir="$root/infra/aws" output -json frontend_urls | python3 -c 'import json,sys; print(json.load(sys.stdin)["home"])')}"
url="${url%/}"
frontend="$url:3001"
out="${OUT:-$root/reports/cloud-ai}"
mkdir -p "$out"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$out/validate-cloud-ai.log"; }
fail() { log "FAIL: $*"; exit 1; }
: > "$out/validate-cloud-ai.log"
log "Cloud AI profile check against $frontend"

# All four services must report ok (the baseline reports them disabled).
curl --fail --silent --show-error "$frontend/health" | tee "$out/01-health.json" | python3 -c '
import json, sys
backend = json.load(sys.stdin)["backend"]
for key in ("ai_mode", "mcp_server", "rag_server", "multi_agent_server"):
    status = (backend.get(key) or {}).get("status")
    print("  %-18s %s" % (key, status))
    assert status == "ok", key
' | tee -a "$out/validate-cloud-ai.log" || fail "an AI service is not ok in the cloud backend health"

product_id="$(curl --fail --silent --show-error "$frontend/partials/products" \
  | python3 -c 'import re,sys; m=re.search("product-row-([0-9]+)", sys.stdin.read()); print(m.group(1) if m else "")')"
[[ -n "$product_id" ]] || fail "no product to review"
log "Using product $product_id"

# B1 AI-Mode: Plan -> Act -> Observe -> Adapt suggestion.
curl --fail --silent --show-error --max-time 300 -X POST "$frontend/ai/suggest" \
  --data-urlencode "name=Aurora Wireless Headphones" --data-urlencode "category=Audio" \
  --data-urlencode "keywords=noise cancelling, 30 hour battery" > "$out/02-ai-mode.html"
grep -qi "observe" "$out/02-ai-mode.html" || fail "AI-Mode returned no agent trace"
grep -qi "disabled by configuration" "$out/02-ai-mode.html" && fail "AI-Mode is still disabled"
log "B1 AI-Mode: suggestion with Plan/Act/Observe trace"

# B2 MCP: check_product_listing tool call.
curl --fail --silent --show-error --max-time 120 -X POST "$frontend/products/$product_id/mcp-check" > "$out/03-mcp.html"
grep -qi "check_product_listing" "$out/03-mcp.html" || fail "MCP tool result missing"
log "B2 MCP: check_product_listing returned"

# B3 RAG: grounded answer that cites a retrieved source.
curl --fail --silent --show-error --max-time 300 -X POST "$frontend/catalogue/ask" \
  --data-urlencode "question=What must a product listing include before it can be published?" > "$out/04-rag.html"
grep -qiE "source|grounded" "$out/04-rag.html" || fail "RAG answer has no retrieved source"
log "B3 RAG: grounded answer with sources"

# B4 Multi-Agent: Planner -> Worker -> Reviewer, then the human decision.
curl --fail --silent --show-error --max-time 60 -X POST "$frontend/products/$product_id/multi-agent" > "$out/05-multi-agent-start.html"
workflow_id="$(python3 -c 'import re,sys; m=re.search(r"multi-agent/([0-9a-f][0-9a-f-]{7,})", open(sys.argv[1]).read()); print(m.group(1) if m else "")' "$out/05-multi-agent-start.html")"
[[ -n "$workflow_id" ]] || fail "Multi-Agent workflow did not start"
log "B4 Multi-Agent: workflow $workflow_id started"
for _ in $(seq 1 90); do
  curl --fail --silent --show-error "$frontend/products/$product_id/multi-agent/$workflow_id" > "$out/06-multi-agent-review.html"
  grep -q 'name="decision"' "$out/06-multi-agent-review.html" && break
  grep -qiE 'stage[^>]*failed|workflow failed' "$out/06-multi-agent-review.html" && fail "Multi-Agent workflow failed"
  sleep 10
done
grep -q 'name="decision"' "$out/06-multi-agent-review.html" || fail "Multi-Agent workflow did not reach Human Review"
log "B4 Multi-Agent: Planner, Worker and Reviewer finished; awaiting Human Review"
curl --fail --silent --show-error -X POST "$frontend/products/$product_id/multi-agent/$workflow_id/review" \
  --data-urlencode "decision=accept" \
  --data-urlencode "feedback=Cloud bonus check: reviewed on AWS and accepted." > "$out/07-multi-agent-decision.html"
log "B4 Multi-Agent: human decision recorded"

printf '{"checked_at":"%s","frontend":"%s","product_id":"%s","workflow_id":"%s","ai_mode":"passed","mcp":"passed","rag":"passed","multi_agent":"passed"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$frontend" "$product_id" "$workflow_id" | tee "$out/cloud-ai-validation.json"
