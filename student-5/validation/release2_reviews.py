"""Release 2 - Student 5 evidence for the shared agentic-loop review modes.

Builds each review subject from real evidence, sends it to the shared AI-Mode
service (POST /agent/validate) and saves the review with its validation log
under docs/evidence/student-5/release-2/<out-dir>/.

    python student-5/validation/release2_reviews.py testing \
        --pre-commit-log reports/student-5-pre-commit.log \
        --endpoint-junit reports/student-5-endpoint-tests.xml \
        --ci-run-id 123456 --ci-status passed --out-dir testing-review-ci
    python student-5/validation/release2_reviews.py multi-agent \
        --review-id <review uuid> --workflow-id <id> --out-dir multi-agent-ui-run
    python student-5/validation/release2_reviews.py cloud --base-url http://<alb-dns> \
        --infrastructure reports/aws-runtime-validation.json --out-dir cloud-review
"""

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET  # noqa: S405 - parses JUnit files this repo's own CI wrote
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = Path(os.getenv("EVIDENCE_DIR", REPO / "docs" / "evidence" / "student-5" / "release-2")).resolve()
AI_MODE_URL = os.getenv("AI_MODE_URL", "http://localhost:7001").rstrip("/")
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8005").rstrip("/")
ENDPOINT_TESTS = REPO / "student-5" / "endpoint-tests" / "test_post_commit_endpoints.py"
OUT = EVIDENCE

# pre-commit hook display names -> hook ids the Testing Review gate expects.
HOOKS = {
    "Ruff security rules": "ruff-security",
    "detect-secrets staged-file scan": "detect-secrets",
    "pip-audit relevant Python requirements": "pip-audit",
}
ENDPOINTS = {
    "create_review": "POST /api/reviews",
    "update_review": "PUT /api/reviews/<id>",
}


def save(name, body):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print("saved", path.relative_to(REPO).as_posix())


def review(mode, subject, name):
    """Run one review mode; save the subject, the review and its validation log."""
    save(name + "-subject.json", {"mode": mode, "subject": subject})
    response = requests.post(
        AI_MODE_URL + "/agent/validate", json={"mode": mode, "subject": subject}, timeout=600
    )
    outcome = response.json()
    save(name + "-review.json", outcome)
    log = (outcome.get("result") or {}).get("validation_log", {})
    print("{}: status={} assessment={} model_reviewed={}".format(
        mode, outcome.get("status"), log.get("authoritative_assessment"), log.get("model_reviewed")))
    return 0 if response.ok else 1


# --------------------------------------------------------------------- testing
def pre_commit_results(log_path):
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    results = []
    for label, hook in HOOKS.items():
        match = re.search(re.escape(label) + r"\.*\s*(Passed|Failed|Skipped)", text)
        status = {"Passed": "passed", "Failed": "failed", "Skipped": "skipped"}.get(
            match.group(1) if match else "", "not_run"
        )
        results.append({"name": hook, "status": status, "phase": "pre_commit",
                        "source": Path(log_path).name})
    return results


def endpoint_results(junit_path, phase="post_commit"):
    cases = ET.parse(junit_path).getroot().iter("testcase")  # noqa: S314 - local CI artefact
    grouped = {name: [] for name in ENDPOINTS}
    for case in cases:
        endpoint = next((name for name in ENDPOINTS if name in case.get("name", "")), None)
        if endpoint is None:
            continue
        failed = any(case.find(tag) is not None for tag in ("failure", "error"))
        skipped = case.find("skipped") is not None
        grouped[endpoint].append("failed" if failed else "skipped" if skipped else "passed")
    results = []
    for endpoint, statuses in grouped.items():
        status = ("not_run" if not statuses else "failed" if "failed" in statuses
                  else "skipped" if "skipped" in statuses else "passed")
        results.append({
            "endpoint": endpoint,
            "route": ENDPOINTS[endpoint],
            "test_ref": "student-5/endpoint-tests/test_post_commit_endpoints.py",
            "phase": phase,
            "status": status,
            "tests": len(statuses),
            "passed": statuses.count("passed"),
        })
    return results


def run_testing(args):
    subject = {
        "student": 5,
        "feature": "Reviews and Ratings",
        "test_code": ENDPOINT_TESTS.read_text(encoding="utf-8"),
        "pre_commit_security_results": pre_commit_results(args.pre_commit_log),
        "post_commit_backend_endpoint_tests": endpoint_results(args.endpoint_junit, args.phase),
        "hosted_ci": {"workflow": "student-5.yml", "run_id": args.ci_run_id,
                      "status": args.ci_status},
    }
    return review("testing_report", subject, "testing-review")


# ----------------------------------------------------------------- multi-agent
def run_multi_agent(args):
    url = "{}/api/reviews/{}/multi-agent/{}".format(BACKEND, args.review_id, args.workflow_id)
    workflow = requests.get(url, timeout=30).json()
    save("multi-agent-workflow.json", workflow)
    return review("multi_agent_workflow", {"workflow": workflow}, "multi-agent-review")


# ----------------------------------------------------------------------- cloud
def _check(check, method, url, expect=200, **kwargs):
    started = time.time()
    try:
        response = requests.request(method, url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        return {"check": check, "url": url, "status": "unavailable", "error": str(exc)}, None
    return {
        "check": check, "url": url, "http_status": response.status_code,
        "status": "passed" if response.status_code == expect else "failed",
        "elapsed_ms": int((time.time() - started) * 1000),
    }, response


def run_cloud(args):
    frontend = "{}:3005".format(args.base_url.rstrip("/"))
    checks = []
    item, _ = _check("frontend", "GET", frontend + "/")
    checks.append(item)
    item, response = _check("backend_database", "GET", frontend + "/health")
    backend = (response.json().get("backend", {}) if response is not None and response.ok else {})
    if item["status"] == "passed" and backend.get("database", {}).get("status") != "ok":
        item["status"] = "failed"
    checks.append(item)

    sku = "SKU-AWS5-{}".format(int(time.time()))
    form = {"product_sku": sku, "user_id": "release2-check", "rating": "4",
            "review": "Created by release2_reviews.py to verify cloud CRUD."}
    crud = {"check": "crud", "status": "failed", "steps": []}
    created, _ = _check("create", "POST", frontend + "/reviews", data=form)
    _, table = _check("read", "GET", frontend + "/partials/reviews", params={"product_sku": sku})
    match = re.search(r'id="review-([0-9a-f-]{36})"', table.text if table is not None else "")
    crud["steps"].append(created)
    review_id = match.group(1) if match else None
    if review_id:
        updated, _ = _check("update", "POST", "{}/reviews/{}".format(frontend, review_id),
                            data=dict(form, rating="2"))
        crud["steps"] += [{"check": "read", "status": "passed", "review_id": review_id}, updated]
    checks.append(crud)

    # AI services are not deployed in the cloud baseline: the Multi-Agent panel
    # must report the workflow unavailable rather than fail the page.
    if review_id:
        item, response = _check("multi_agent_unavailable", "POST",
                                "{}/reviews/{}/multi-agent".format(frontend, review_id), expect=503)
        if response is not None and "Multi-Agent workflow unavailable" not in response.text:
            item["status"] = "failed"
        checks.append(item)
        deleted, _ = _check("delete", "POST", "{}/reviews/{}/delete".format(frontend, review_id))
        crud["steps"].append(deleted)
    if review_id and all(step["status"] == "passed" for step in crud["steps"]):
        crud["status"] = "passed"
    checks.append({"check": "ai_mode_not_deployed",
                   "status": "passed" if backend.get("ai_mode", {}).get("status") != "ok" else "failed",
                   "detail": backend.get("ai_mode")})

    infrastructure = []
    for path in args.infrastructure:
        try:
            content = json.loads(Path(path).read_text(encoding="utf-8"))
            infrastructure.append({"name": Path(path).name, "status": "passed", "content": content})
        except (OSError, ValueError) as exc:
            infrastructure.append({"name": Path(path).name, "status": "unavailable", "error": str(exc)})
    subject = {"student": 5, "feature": "Reviews and Ratings", "platform": "AWS",
               "infrastructure_evidence": infrastructure, "runtime_checks": checks}
    return review("cloud_deployment_report", subject, "cloud-deployment-review")


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    testing = commands.add_parser("testing", help="Testing Report Review")
    testing.add_argument("--pre-commit-log", required=True)
    testing.add_argument("--endpoint-junit", required=True)
    testing.add_argument("--ci-run-id", default=None)
    testing.add_argument("--ci-status", choices=("passed", "failed", "not_run"), default="not_run")
    testing.add_argument("--phase", choices=("post_commit", "local"), default="post_commit",
                         help="post_commit for the student-5.yml artifact; local for a local run")

    multi = commands.add_parser("multi-agent", help="Multi-Agent Workflow Review")
    multi.add_argument("--review-id", required=True)
    multi.add_argument("--workflow-id", required=True)

    cloud = commands.add_parser("cloud", help="Cloud Deployment Report Review")
    cloud.add_argument("--base-url", required=True, help="http://<load balancer DNS name>")
    cloud.add_argument("--infrastructure", nargs="+", default=[],
                       help="infrastructure evidence JSON, e.g. reports/aws-runtime-validation.json")

    for sub in (testing, multi, cloud):
        sub.add_argument("--out-dir", default="", help="subfolder of docs/evidence/student-5/release-2/")

    args = parser.parse_args()
    OUT = EVIDENCE / args.out_dir if args.out_dir else EVIDENCE
    return {"testing": run_testing, "multi-agent": run_multi_agent, "cloud": run_cloud}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
