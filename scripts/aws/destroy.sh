#!/usr/bin/env bash
# Tear down the whole group deployment so it stops costing money.
# Usage: AWS_REGION=ap-southeast-2 TF_STATE_BUCKET=<bucket> bash scripts/aws/destroy.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
export TF_VAR_aws_region="${AWS_REGION:-ap-southeast-2}"

if [[ "${APPROVE_DESTROY:-}" != "YES" ]]; then
  [[ -t 0 ]] || { echo "Set APPROVE_DESTROY=YES to destroy without a prompt." >&2; exit 2; }
  read -r -p "Destroy the whole AWS deployment, including the EFS database data? Type DESTROY: " answer
  [[ "$answer" == "DESTROY" ]] || { echo "Destroy cancelled."; exit 1; }
fi

bash "$root/scripts/aws/init.sh"
terraform -chdir="$root/infra/aws" destroy -input=false -auto-approve -var="image_tag=bootstrap"
echo "All deployed resources are destroyed. The Terraform state bucket ${TF_STATE_BUCKET} is kept"
echo "(a few cents a month); delete it in S3 once the group no longer needs the state."
