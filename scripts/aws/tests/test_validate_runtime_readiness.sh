#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/../../.." && pwd)"
runtime="$root/scripts/aws/validate-runtime.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 - "$runtime" "$tmp" <<'PY'
import json
import sys
from pathlib import Path

script = Path(sys.argv[1]).read_text()
tmp = Path(sys.argv[2])

def extract(marker: str) -> str:
    start = script.index(marker) + len(marker)
    end = script.index("\nPY", start)
    return script[start:end]

service_gate = extract('''    python3 - "$batch_json" <<'PY' || return 1''')
target_gate = extract('''    python3 - "$target_json" <<'PY' || return 1''')
(tmp / "service-gate.py").write_text(service_gate)
(tmp / "target-gate.py").write_text(target_gate)

def service(primary_status="PRIMARY", desired=1, running=1, pending=0,
            rollout="IN_PROGRESS", previous=True):
    deployments = [{
        "status": primary_status,
        "desiredCount": desired,
        "runningCount": running,
        "pendingCount": pending,
        "rolloutState": rollout,
    }]
    if previous:
        deployments.append({
            "status": "ACTIVE",
            "desiredCount": 0,
            "runningCount": 0,
            "pendingCount": 0,
            "rolloutState": "COMPLETED",
        })
    return {
        "services": [{
            "serviceName": "frontend",
            "status": "ACTIVE",
            "desiredCount": 1,
            "runningCount": 1,
            "pendingCount": 0,
            "deployments": deployments,
        }],
    }

nonzero_previous = service()
nonzero_previous["services"][0]["deployments"][1]["pendingCount"] = 1
cases = {
    "primary-with-zero-count-old-deployment": (service(), True),
    "pending-primary": (service(pending=1), False),
    "missing-primary-tasks": (service(running=0), False),
    "missing-primary-deployment": (service(primary_status="ACTIVE"), False),
    "failed-primary-rollout": (service(rollout="FAILED"), False),
    "nonzero-superseded-deployment": (nonzero_previous, False),
}
for name, (payload, _) in cases.items():
    (tmp / f"{name}.json").write_text(json.dumps(payload))
(tmp / "unhealthy-target.json").write_text(json.dumps({
    "TargetHealthDescriptions": [{"TargetHealth": {"State": "unhealthy"}}],
}))
PY

run_service_gate() {
  python3 "$tmp/service-gate.py" "$(cat "$tmp/$1.json")"
}

if ! run_service_gate primary-with-zero-count-old-deployment; then
  echo "Expected a healthy PRIMARY with a zero-count old deployment to pass." >&2
  exit 1
fi
for case in pending-primary missing-primary-tasks missing-primary-deployment failed-primary-rollout; do
  if run_service_gate "$case"; then
    echo "Expected $case to block ECS readiness." >&2
    exit 1
  fi
done

if python3 "$tmp/target-gate.py" "$(cat "$tmp/unhealthy-target.json")"; then
  echo "Expected unhealthy ALB targets to block readiness." >&2
  exit 1
fi

health_gate_line="$(grep -nE '^[[:space:]]*wait_for_healthy_targets$' "$runtime" | cut -d: -f1)"
crud_line="$(grep -nF 'smoke_curl POST "$student3_url/customers"' "$runtime" | cut -d: -f1)"
if [[ -z "$health_gate_line" || -z "$crud_line" || "$health_gate_line" -ge "$crud_line" ]]; then
  echo "Expected ALB readiness to run before the first CRUD request." >&2
  exit 1
fi

echo "ECS/ALB readiness regression checks passed."
