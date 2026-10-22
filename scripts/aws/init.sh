#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
region="${AWS_REGION:-ap-southeast-2}"
bucket="${TF_STATE_BUCKET:-}"
[[ -n "$bucket" ]] || { echo "Set TF_STATE_BUCKET before initializing Terraform." >&2; exit 2; }

bash "$root/scripts/aws/bootstrap-state.sh"
terraform -chdir="$root/infra/aws" init \
  -backend-config="bucket=$bucket" \
  -backend-config="key=asd-2026/group-application/terraform.tfstate" \
  -backend-config="region=$region" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
terraform -chdir="$root/infra/aws" validate
