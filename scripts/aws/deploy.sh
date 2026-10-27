#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
tag="${IMAGE_TAG:-$(git -C "$root" rev-parse HEAD)}"
[[ "$tag" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || { echo "IMAGE_TAG is invalid." >&2; exit 2; }
if [[ "${APPROVE_DEPLOYMENT:-}" != "YES" ]]; then
  [[ -t 0 ]] || { echo "Set APPROVE_DEPLOYMENT=YES after reviewing the plan." >&2; exit 2; }
  read -r -p "Apply AWS infrastructure and deploy group image $tag? Type DEPLOY: " answer
  [[ "$answer" == "DEPLOY" ]] || { echo "Deployment cancelled."; exit 1; }
fi

# Terraform and the image push must target the same region.
export TF_VAR_aws_region="${AWS_REGION:-ap-southeast-2}"
mkdir -p "$root/reports"

bash "$root/scripts/aws/init.sh"
# Approval was given above (DEPLOY or APPROVE_DEPLOYMENT=YES); GitHub Actions has no terminal to answer a prompt.
terraform -chdir="$root/infra/aws" apply -input=false -auto-approve -var="image_tag=bootstrap" -target=aws_ecr_repository.services
IMAGE_TAG="$tag" bash "$root/scripts/aws/build-push-images.sh"
terraform -chdir="$root/infra/aws" apply -input=false -auto-approve -var="image_tag=$tag"
terraform -chdir="$root/infra/aws" output -json | tee "$root/reports/aws-deployment-outputs.json"
bash "$root/scripts/aws/validate-runtime.sh"
