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

bash "$root/scripts/aws/init.sh"
terraform -chdir="$root/infra/aws" apply -var="image_tag=bootstrap" -target=aws_ecr_repository.services
IMAGE_TAG="$tag" bash "$root/scripts/aws/build-push-images.sh"
terraform -chdir="$root/infra/aws" apply -var="image_tag=$tag" -auto-approve
terraform -chdir="$root/infra/aws" output -json | tee "$root/reports/aws-deployment-outputs.json"
bash "$root/scripts/aws/validate-runtime.sh"
