#!/usr/bin/env bash
# Switch the deployed group application between the required cloud baseline (AI off) and
# the bonus cloud AI profile, reusing the application images that are already deployed.
#   bash scripts/aws/enable-cloud-ai.sh          # build/push ai-services, enable, validate
#   bash scripts/aws/enable-cloud-ai.sh disable  # back to the baseline, AI services removed
# Needs TF_STATE_BUCKET and APPROVE_DEPLOYMENT=YES, like deploy.sh.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
mode="${1:-enable}"
region="${AWS_REGION:-ap-southeast-2}"
prefix="${TF_VAR_name_prefix:-asd26-g40-r2}"
export TF_VAR_aws_region="$region"
[[ "$mode" == "enable" || "$mode" == "disable" ]] || { echo "Usage: $0 [enable|disable]" >&2; exit 2; }
[[ "${APPROVE_DEPLOYMENT:-}" == "YES" ]] || { echo "Set APPROVE_DEPLOYMENT=YES to change the AWS deployment." >&2; exit 2; }

# Keep every application service on the image it already runs, so only AI settings change.
task_definition="$(aws ecs describe-services --region "$region" --cluster "$prefix-cluster" \
  --services "$prefix-student-1-backend" --query 'services[0].taskDefinition' --output text)"
app_tag="$(aws ecs describe-task-definition --region "$region" --task-definition "$task_definition" \
  --query 'taskDefinition.containerDefinitions[0].image' --output text)"
app_tag="${app_tag##*:}"
echo "Application image tag: $app_tag"

bash "$root/scripts/aws/init.sh"
tf() { terraform -chdir="$root/infra/aws" "$@"; }

if [[ "$mode" == "disable" ]]; then
  tf apply -input=false -auto-approve -var="image_tag=$app_tag" -var="enable_cloud_ai=false"
  aws ecs wait services-stable --region "$region" --cluster "$prefix-cluster" \
    --services "$prefix-student-1-backend" "$prefix-student-3-backend" "$prefix-student-5-backend"
  bash "$root/scripts/aws/validate-runtime.sh"
  exit 0
fi

tf apply -input=false -auto-approve -var="image_tag=$app_tag" -var="enable_cloud_ai=true" \
  -target=aws_ecr_repository.cloud_ai
ai_tag="ai-$(git -C "$root" rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)"
registry="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$region.amazonaws.com"
image="$registry/$prefix/ai-services:$ai_tag"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
docker build --pull -f "$root/ai-services/Dockerfile.cloud" -t "$image" "$root/ai-services"
docker push "$image"

tf apply -input=false -auto-approve -var="image_tag=$app_tag" -var="enable_cloud_ai=true" \
  -var="cloud_ai_image_tag=$ai_tag"
echo "Waiting for the AI task (model download included) and the updated backends..."
aws ecs wait services-stable --region "$region" --cluster "$prefix-cluster" \
  --services "$prefix-ai-services" "$prefix-student-1-backend" "$prefix-student-3-backend" \
  "$prefix-student-5-backend"
# The task is running before Ollama has finished pulling its models; wait until the
# Student 1 backend reports all four AI services ok (up to 20 minutes).
student1="$(tf output -json frontend_urls | python3 -c 'import json,sys; print(json.load(sys.stdin)["student_1"])')"
for attempt in $(seq 1 80); do
  if curl --silent --max-time 10 "$student1/health" | python3 -c '
import json, sys
backend = json.load(sys.stdin)["backend"]
sys.exit(0 if all((backend.get(k) or {}).get("status") == "ok"
                  for k in ("ai_mode", "mcp_server", "rag_server", "multi_agent_server")) else 1)
' 2>/dev/null; then
    echo "All four AI services ready."
    break
  fi
  [[ "$attempt" == 80 ]] && { echo "AI services not ready after 20 minutes." >&2; exit 1; }
  sleep 15
done
EXPECT_CLOUD_AI=enabled bash "$root/scripts/aws/validate-runtime.sh"
bash "$root/scripts/aws/validate-cloud-ai.sh"
