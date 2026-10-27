#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
region="${AWS_REGION:-ap-southeast-2}"
tag="${IMAGE_TAG:-$(git -C "$root" rev-parse HEAD)}"
tag="${tag:0:40}"
prefix="${TF_VAR_name_prefix:-asd26-g40-r2}"
registry="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$region.amazonaws.com"

aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

build_push() {
  local name="$1" context="$2" dockerfile="$3"
  local image="$registry/$prefix/$name:$tag"
  local build_dir="$root/$context" dockerfile_path="$root/$dockerfile"
  if [[ "$name" == student-*-frontend ]]; then
    # Compose mounts shared/ (team theme and JS) into these frontends at /app/shared;
    # the cloud image has to carry its own copy or every /shared/... asset is a 404.
    build_dir="$(mktemp -d)"
    cp -r "$root/$context/." "$build_dir/"
    cp -r "$root/shared" "$build_dir/shared"
    dockerfile_path="$build_dir/$(basename "$dockerfile")"
  fi
  docker build --pull -f "$dockerfile_path" -t "$image" "$build_dir"
  docker push "$image"
  [[ "$build_dir" == "$root/$context" ]] || rm -rf "$build_dir"
}

build_push shared-home shared shared/Dockerfile
build_push student-1-db student-1/database student-1/database/Dockerfile
build_push student-1-backend student-1/backend student-1/backend/Dockerfile
build_push student-1-frontend student-1/frontend student-1/frontend/Dockerfile
build_push student2-db student-2 student-2/database-api/Dockerfile
build_push student2-api student-2 student-2/backend/Dockerfile
build_push student2-frontend student-2 student-2/frontend/Dockerfile
build_push student-3-db student-3/database student-3/database/Dockerfile
build_push student-3-backend student-3/backend student-3/backend/Dockerfile
build_push student-3-frontend student-3/frontend student-3/frontend/Dockerfile
build_push student-4-db student-4/database student-4/database/Dockerfile
build_push student-4-backend student-4/backend student-4/backend/Dockerfile
build_push student-4-frontend student-4/frontend student-4/frontend/Dockerfile
build_push student-5-db student-5/database student-5/database/Dockerfile
build_push student-5-backend student-5/backend student-5/backend/Dockerfile
build_push student-5-frontend student-5/frontend student-5/frontend/Dockerfile
echo "Published all group application images with tag $tag"
