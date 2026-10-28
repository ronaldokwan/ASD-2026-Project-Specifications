#!/usr/bin/env python3
"""Run the Student 1 listing review (Planner -> Worker -> Reviewer -> Human) from a terminal.

    python scripts/student-1-multi-agent.py start  --product-id 1 --wait
    python scripts/student-1-multi-agent.py status --product-id 1 --workflow-id <id>
    python scripts/student-1-multi-agent.py history --product-id 1
    python scripts/student-1-multi-agent.py review --product-id 1 --workflow-id <id> \\
        --decision accept --feedback "Ready to publish."

Every call goes through the Student 1 backend/API, the same path the frontend uses.
"""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API_URL = os.getenv("STUDENT1_API_URL", "http://localhost:8001").rstrip("/")
_API_ORIGIN = urlsplit(API_URL)
if (_API_ORIGIN.scheme not in ("http", "https") or not _API_ORIGIN.hostname
        or _API_ORIGIN.username or _API_ORIGIN.password):
    raise SystemExit("STUDENT1_API_URL must be an HTTP(S) URL without embedded credentials.")

RUNNING = ("queued", "planning", "working", "reviewing", "revising")


def call(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(API_URL + path, data=data, method=method,  # noqa: S310 - API_URL is validated as HTTP(S) above
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=180) as response:  # noqa: S310 - API_URL is validated as HTTP(S) above
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.load(exc)
        except ValueError:
            detail = {"error": exc.reason}
        raise RuntimeError("HTTP {}: {}".format(exc.code, json.dumps(detail))) from exc
    except URLError as exc:
        raise RuntimeError("Student 1 backend is unavailable: {}".format(exc.reason)) from exc


def path(product_id, *parts):
    return "/".join(["/api/products/{}/multi-agent".format(product_id), *parts])


def show(workflow):
    print(json.dumps(workflow, indent=2))
    print("\n== {} ({})".format(workflow.get("status"), workflow.get("stage")), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start a listing readiness review")
    start.add_argument("--product-id", type=int, required=True)
    start.add_argument("--wait", action="store_true", help="poll until human review or failure")

    status = commands.add_parser("status", help="show workflow stages and decision")
    status.add_argument("--product-id", type=int, required=True)
    status.add_argument("--workflow-id", required=True)
    status.add_argument("--wait", action="store_true", help="poll until human review or failure")

    history = commands.add_parser("history", help="list workflows for a product")
    history.add_argument("--product-id", type=int, required=True)

    review = commands.add_parser("review", help="record the human decision")
    review.add_argument("--product-id", type=int, required=True)
    review.add_argument("--workflow-id", required=True)
    review.add_argument("--decision", choices=("accept", "partial_accept", "reject"), required=True)
    review.add_argument("--feedback", default="")
    review.add_argument("--corrected-recommendation")
    review.add_argument("--corrected-rationale")
    review.add_argument("--accepted-field", action="append", default=[])
    review.add_argument("--unresolved-issue", action="append", default=[])

    args = parser.parse_args()
    try:
        if args.command == "start":
            started = call("POST", path(args.product_id), {})
            print(json.dumps(started, indent=2))
            if not args.wait:
                return 0
            args.workflow_id = started["workflow_id"]
            args.command = "status"

        if args.command == "status":
            while True:
                workflow = call("GET", path(args.product_id, args.workflow_id))
                if not args.wait or workflow.get("status") not in RUNNING:
                    break
                print("... {} ({})".format(workflow["status"], workflow["stage"]), file=sys.stderr)
                time.sleep(3)
            show(workflow)
            return 1 if workflow.get("status") == "failed" else 0

        if args.command == "history":
            print(json.dumps(call("GET", path(args.product_id, "history")), indent=2))
            return 0

        payload = {"decision": args.decision, "feedback": args.feedback}
        if args.decision == "partial_accept":
            payload.update({
                "corrected_output": {
                    "recommendation": args.corrected_recommendation or "",
                    "rationale": args.corrected_rationale or "",
                },
                "accepted_fields": args.accepted_field,
                "unresolved_issues": args.unresolved_issue,
            })
        elif args.decision == "reject":
            payload["unresolved_issues"] = args.unresolved_issue
        show(call("POST", path(args.product_id, args.workflow_id, "review"), payload))
        return 0
    except (RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
