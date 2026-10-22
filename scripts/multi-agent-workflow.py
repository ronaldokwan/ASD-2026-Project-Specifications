#!/usr/bin/env python3
"""Start, inspect and human-review a Student 3 loyalty workflow from a terminal."""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


API_URL = os.getenv("STUDENT3_API_URL", "http://localhost:8003").rstrip("/")
_API_ORIGIN = urlsplit(API_URL)
if (_API_ORIGIN.scheme not in ("http", "https") or not _API_ORIGIN.hostname
        or _API_ORIGIN.username or _API_ORIGIN.password):
    raise SystemExit("STUDENT3_API_URL must be an HTTP(S) URL without embedded credentials.")


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
        raise RuntimeError("Student 3 backend is unavailable: {}".format(exc.reason)) from exc


def workflow_path(customer_id, workflow_id=None, suffix=""):
    base = "/api/customers/{}/multi-agent".format(customer_id)
    return base + ("/{}".format(workflow_id) if workflow_id else "") + suffix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start a customer loyalty review")
    start.add_argument("--customer-id", type=int, required=True)
    start.add_argument("--wait", action="store_true", help="wait for model stages to finish")

    status = commands.add_parser("status", help="show workflow stages and decision")
    status.add_argument("--customer-id", type=int, required=True)
    status.add_argument("--workflow-id", required=True)
    status.add_argument("--wait", action="store_true", help="poll until human review or failure")

    review = commands.add_parser("review", help="record a human decision")
    review.add_argument("--customer-id", type=int, required=True)
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
            result = call("POST", workflow_path(args.customer_id), {})
            print(json.dumps(result, indent=2))
            if args.wait:
                args.command = "status"
                args.workflow_id = result["workflow_id"]
            else:
                return 0

        if args.command == "status":
            while True:
                result = call("GET", workflow_path(args.customer_id, args.workflow_id))
                print(json.dumps(result, indent=2))
                if not args.wait or result.get("status") not in (
                    "queued", "planning", "working", "reviewing", "revising",
                ):
                    break
                time.sleep(2)
            return 0 if result.get("status") != "failed" else 1

        if args.command == "review":
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
            result = call("POST", workflow_path(args.customer_id, args.workflow_id, "/review"), payload)
            print(json.dumps(result, indent=2))
            return 0
    except (RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
