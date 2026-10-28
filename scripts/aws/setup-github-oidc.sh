#!/usr/bin/env bash
# One-off: create the GitHub OIDC provider and the deploy role cloud-deployment.yml assumes.
# Run with AWS administrator credentials (not from GitHub Actions).
# Usage: AWS_REGION=ap-southeast-2 TF_STATE_BUCKET=<bucket> bash scripts/aws/setup-github-oidc.sh
# Set CREATE_OIDC_PROVIDER=false if the account already has token.actions.githubusercontent.com.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
region="${AWS_REGION:-ap-southeast-2}"
bucket="${TF_STATE_BUCKET:-}"
[[ -n "$bucket" ]] || { echo "Set TF_STATE_BUCKET (the same bucket deploy.sh uses)." >&2; exit 2; }
dir="$root/infra/aws/github-oidc"

bash "$root/scripts/aws/bootstrap-state.sh"
terraform -chdir="$dir" init -input=false \
  -backend-config="bucket=$bucket" \
  -backend-config="key=asd-2026/github-oidc/terraform.tfstate" \
  -backend-config="region=$region" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
terraform -chdir="$dir" apply -input=false \
  -var="aws_region=$region" \
  -var="tf_state_bucket=$bucket" \
  -var="create_oidc_provider=${CREATE_OIDC_PROVIDER:-true}"

role_arn="$(terraform -chdir="$dir" output -raw deploy_role_arn)"
cat <<EOF

Deploy role ready: $role_arn
Next, give it to the aws-production GitHub environment (see docs/reports/release-2-student-1.md §6):
  gh variable set AWS_DEPLOY_ROLE_ARN --env aws-production --body "$role_arn"
  gh variable set TF_STATE_BUCKET     --env aws-production --body "$bucket"
  gh variable set AWS_REGION          --env aws-production --body "$region"
EOF
