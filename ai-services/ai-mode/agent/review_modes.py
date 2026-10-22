"""Structured assessment-report reviews with deterministic evidence gates."""

import uuid


COMMON = {
    "findings": {"type": "string", "min_words": 1, "max_words": 100},
    "risks": {"type": "string", "min_words": 1, "max_words": 100},
    "recommendations": {"type": "string", "min_words": 1, "max_words": 100},
}

REVIEW_MODES = {
    "multi_agent_workflow": {
        "goal": "multi_agent_workflow_review",
        "assessment": {"type": "enum", "values": ["supported", "issues_found", "incomplete"]},
        "dimensions": {"workflow_review": {"type": "string", "min_words": 1, "max_words": 100}},
        "task": (
            "Review the supplied Planner, Worker and Reviewer outputs, evidence references, "
            "stage states and human decision. Identify unsupported claims, contradictions, "
            "defects, risks and missing information. The orchestration state and recorded "
            "human decision are authoritative; do not turn failed or incomplete stages into success."
        ),
    },
    "testing_report": {
        "goal": "testing_report_review",
        "assessment": {"type": "enum", "values": ["passed", "failed", "incomplete"]},
        "dimensions": {
            "test_code_review": {"type": "string", "min_words": 1, "max_words": 100},
            "execution_results_review": {"type": "string", "min_words": 1, "max_words": 100},
        },
        "task": (
            "Review test code separately from actual test execution results. Check coverage, "
            "meaningful assertions, endpoint identity, reported exit codes and contradictions. "
            "Review pre-commit Ruff security, detect-secrets and pip-audit results separately "
            "from backend endpoint-test results. Each endpoint test must be identified as a "
            "post-commit local run or a hosted GitHub Actions post-push run. Review hosted CI "
            "as a separate evidence source and state whether it has run; local results are not "
            "hosted CI results. Execution evidence is authoritative: never mark failed, "
            "skipped, missing, pre-commit-only or unexecuted required checks as passed."
        ),
    },
    "cloud_deployment_report": {
        "goal": "cloud_deployment_report_review",
        "assessment": {"type": "enum", "values": ["ready", "blocked", "incomplete"]},
        "dimensions": {
            "infrastructure_review": {"type": "string", "min_words": 1, "max_words": 100},
            "runtime_review": {"type": "string", "min_words": 1, "max_words": 100},
        },
        "task": (
            "Review infrastructure/resource evidence separately from runtime evidence. "
            "Check resource boundaries, persistence, expected HTTP responses, frontend to "
            "backend to database flow, CRUD, failures and logs. Missing or failed runtime "
            "evidence must not be reported as healthy. The supplied deterministic checks are authoritative."
        ),
    },
}


def schema_for(mode):
    spec = REVIEW_MODES[mode]
    return {
        **spec["dimensions"],
        "assessment": spec["assessment"],
        **COMMON,
    }


def task_for(mode):
    return REVIEW_MODES[mode]["task"]


def _status(item):
    if not isinstance(item, dict):
        return "unknown"
    if item.get("status") in ("passed", "failed", "skipped", "unavailable", "not_run"):
        return item["status"]
    code = item.get("exit_code")
    if type(code) is int:
        return "passed" if code == 0 else "failed"
    return "unknown"


def _endpoint_origin(item):
    """Return a recognized origin for an endpoint test run, if it is post-commit."""
    if not isinstance(item, dict) or item.get("phase") != "post_commit":
        return None
    origin = item.get("origin", "local")  # Backward-compatible evidence defaults to local.
    return origin if origin in ("local", "github_actions") else None


def evidence_gate(mode, subject):
    """Return the authoritative state from supplied deterministic evidence."""
    if mode == "testing_report":
        code = subject.get("test_code")
        security = subject.get("pre_commit_security_results")
        endpoint_tests = subject.get("post_commit_backend_endpoint_tests")
        hosted_ci = subject.get("hosted_ci")
        if not isinstance(code, str) or not code.strip():
            return "incomplete", "Test code evidence is missing."

        required_hooks = {"ruff-security", "detect-secrets", "pip-audit"}
        if not isinstance(security, list):
            security = []
        observed_hooks = {
            item.get("name"): _status(item)
            for item in security if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        missing_hooks = sorted(required_hooks - set(observed_hooks))
        failed_hooks = sorted(name for name, status in observed_hooks.items()
                              if name in required_hooks and status == "failed")
        unknown_hooks = sorted(name for name in required_hooks & set(observed_hooks)
                               if observed_hooks[name] != "passed" and name not in failed_hooks)

        if not isinstance(endpoint_tests, list):
            endpoint_tests = []
        post_commit_tests = [item for item in endpoint_tests if _endpoint_origin(item)]
        endpoint_names = {item.get("endpoint") or item.get("name") for item in post_commit_tests}
        endpoint_names.discard(None)
        failed_tests = sorted(str(item.get("endpoint") or item.get("name") or "unnamed endpoint test")
                              for item in endpoint_tests if isinstance(item, dict) and _status(item) == "failed")
        unknown_tests = sorted(str(item.get("endpoint") or item.get("name") or "unnamed endpoint test")
                               for item in endpoint_tests if isinstance(item, dict) and _status(item) != "passed"
                               and str(item.get("endpoint") or item.get("name") or "unnamed endpoint test") not in failed_tests)
        unexecuted_hooks = sorted(name for name in required_hooks & set(observed_hooks)
                                  if observed_hooks[name] in ("skipped", "unavailable", "not_run"))
        missing_test_evidence = not endpoint_tests
        too_few_endpoint_tests = len(endpoint_names) < 2
        unqualified_tests = bool(endpoint_tests) and not post_commit_tests

        failures = []
        if failed_hooks:
            failures.append("failed pre-commit security hooks: " + ", ".join(failed_hooks))
        if failed_tests:
            failures.append("failed post-commit backend endpoint tests: " + ", ".join(failed_tests))
        if failures:
            details = "; ".join(failures)
            if missing_hooks:
                details += "; missing security results: " + ", ".join(missing_hooks)
            if missing_test_evidence or unqualified_tests or too_few_endpoint_tests:
                details += "; post-commit evidence is incomplete"
            return "failed", details + "."

        ci_status = _status(hosted_ci)
        if ci_status == "failed":
            return "failed", "GitHub Actions required validation failed."

        incomplete = []
        if missing_hooks:
            incomplete.append("missing pre-commit security results: " + ", ".join(missing_hooks))
        if unknown_hooks or unexecuted_hooks:
            incomplete.append("security hooks without a pass result: " + ", ".join(sorted(set(unknown_hooks + unexecuted_hooks))))
        if missing_test_evidence:
            incomplete.append("post-commit backend endpoint-test results are missing")
        elif unqualified_tests:
            incomplete.append("backend endpoint tests are not identified as post-commit local or hosted post-push runs")
        if too_few_endpoint_tests:
            incomplete.append("at least two distinct post-commit backend endpoint tests are required")
        if unknown_tests:
            incomplete.append("backend endpoint tests without a pass result: " + ", ".join(unknown_tests))
        if ci_status != "passed":
            incomplete.append("successful GitHub Actions validation evidence is missing or was not run")
        if incomplete:
            return "incomplete", "; ".join(incomplete) + "."
        return "passed", "All three pre-commit security hooks and at least two post-commit backend endpoint tests passed."

    if mode == "cloud_deployment_report":
        infrastructure = subject.get("infrastructure_evidence")
        runtime = subject.get("runtime_checks")
        if not isinstance(infrastructure, list) or not infrastructure or not isinstance(runtime, list) or not runtime:
            return "incomplete", "Infrastructure evidence and runtime checks are both required."
        statuses = [_status(item) for item in infrastructure + runtime]
        if any(status in ("failed", "unavailable") for status in statuses):
            return "blocked", "At least one infrastructure or runtime check failed or was unavailable."
        if any(status != "passed" for status in statuses):
            return "incomplete", "At least one infrastructure or runtime check is unverified."
        required_runtime = {"frontend", "backend_database", "crud"}
        observed = {item.get("check") for item in runtime if isinstance(item, dict)}
        if not required_runtime.issubset(observed):
            return "incomplete", "Runtime evidence must include frontend, backend/database and CRUD checks."
        return "ready", "All supplied infrastructure and required runtime checks passed."

    workflow = subject.get("workflow")
    if not isinstance(workflow, dict):
        return "incomplete", "A workflow record is required."
    if workflow.get("status") in ("failed", "queued", "planning", "working", "reviewing", "revising"):
        return "issues_found", "The workflow has a failed or incomplete orchestration state."
    gate = workflow.get("completion_gate") or {}
    if not all(gate.get(key) for key in ("planner_completed", "worker_completed", "reviewer_completed")):
        return "incomplete", "One or more model stages are incomplete."
    if not gate.get("human_decision_recorded"):
        return "incomplete", "The human decision has not been recorded."
    if workflow.get("status") == "rejected":
        return "issues_found", "The human decision rejected the result."
    if workflow.get("status") == "partially_accepted" and not (workflow.get("human_decision") or {}).get("unresolved_issues"):
        return "incomplete", "Partial acceptance must retain unresolved issues."
    return "supported", "All model stages and a human decision are present."


def finalize_review(mode, subject, outcome):
    """Apply deterministic gates and attach an inspectable validation record."""
    expected, explanation = evidence_gate(mode, subject)
    model_result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
    model_assessment = model_result.get("assessment")
    model_reviewed = not outcome.get("fallback_used", False)
    authoritative = expected
    if not model_reviewed:
        authoritative = "incomplete"
        explanation = "The model review did not execute; no successful model review is claimed. " + explanation
    elif mode == "testing_report":
        authoritative = expected if expected != "passed" else model_assessment
    elif mode == "cloud_deployment_report":
        authoritative = expected if expected != "ready" else model_assessment
    elif mode == "multi_agent_workflow":
        authoritative = expected if expected != "supported" else model_assessment

    result = dict(model_result)
    result["assessment"] = authoritative
    review_id = str(uuid.uuid4())
    result["validation_log"] = {
        "review_id": review_id,
        "mode": mode,
        "model_reviewed": model_reviewed,
        "model_assessment": model_assessment,
        "evidence_assessment": expected,
        "authoritative_assessment": authoritative,
        "contradiction": bool(model_assessment and model_assessment != expected),
        "evidence_gate": explanation,
    }
    if mode == "testing_report" and expected in ("failed", "incomplete"):
        corrections = ["Authoritative testing evidence: " + explanation]
        supplied_endpoint_tests = subject.get("post_commit_backend_endpoint_tests")
        if isinstance(supplied_endpoint_tests, list) and any(
            isinstance(item, dict) and _endpoint_origin(item) is None
            for item in supplied_endpoint_tests
        ):
            corrections.append("Some backend endpoint results are not identified as post-commit local or hosted post-push executions.")
        elif isinstance(supplied_endpoint_tests, list) and supplied_endpoint_tests and all(
            _endpoint_origin(item) == "local" for item in supplied_endpoint_tests if isinstance(item, dict)
        ):
            corrections.append("These endpoint results are local executions, not GitHub Actions post-push results.")
        if _status(subject.get("hosted_ci")) != "passed":
            corrections.append("GitHub Actions has not passed; local test results are not hosted CI results.")
        gate_finding = " ".join(corrections)
        existing = result.get("findings", "")
        result["findings"] = (existing.rstrip() + " " + gate_finding).strip()[:1600]
        result["execution_results_review"] = (
            (result.get("execution_results_review", "").rstrip() + " " + gate_finding).strip()[:1600]
        )
    outcome["result"] = result
    outcome["review_id"] = review_id
    outcome["mode"] = mode + "_review"
    if not model_reviewed:
        outcome["ok"] = False
        outcome["status"] = "incomplete"
    elif authoritative in ("failed", "blocked", "issues_found"):
        outcome["status"] = "blocked"
    elif authoritative == "incomplete":
        outcome["status"] = "incomplete"
    else:
        outcome["status"] = "reviewed"
    return outcome
