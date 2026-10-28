"""Student 5 adapter for the shared Multi-Agent moderation workflow.

frontend -> backend/API -> shared Multi-Agent Server -> Planner -> Worker -> Reviewer -> Human Review

Mirrors Student 3's student-3/backend/app/multi_agent_client.py: same shared
service, same request/evidence contract, adapted to review moderation instead
of loyalty benefits.
"""

import json

import requests

from . import mcp_client
from .config import Config


class MultiAgentUnavailable(RuntimeError):
    """The shared Multi-Agent service is disabled or unreachable."""


class MultiAgentBadResponse(RuntimeError):
    """The shared Multi-Agent service returned an invalid response."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _subject_ref(review_id):
    return "student-5-review:{}".format(review_id)


def _call(method, path, **kwargs):
    url = Config.MULTI_AGENT_URL + path
    try:
        response = requests.request(method, url, timeout=Config.MULTI_AGENT_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise MultiAgentUnavailable("Multi-Agent service is unreachable") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise MultiAgentBadResponse("Multi-Agent service returned non-JSON data") from exc
    if response.status_code == 404:
        raise MultiAgentBadResponse(body.get("error", "workflow not found"), status=404)
    if response.status_code >= 500:
        raise MultiAgentUnavailable(body.get("error", "Multi-Agent service is unavailable"))
    if response.status_code >= 400:
        raise MultiAgentBadResponse(
            body.get("error", "workflow request was rejected"),
            status=response.status_code,
        )
    return body


def start_review_moderation(review, stats):
    if not Config.MULTI_AGENT_ENABLED:
        raise MultiAgentUnavailable("Multi-Agent integration is disabled")

    facts = {
        "review_id": review["review_id"],
        "product_sku": review["product_sku"],
        "rating": review["rating"],
        "review_text": review["review"],
        "existing_review_count": stats.get("review_count", 0),
        "average_rating": stats.get("avg_rating"),
    }
    evidence = [{
        "id": "review_facts",
        "source": "student-5-reviews-db",
        "status": "available",
        "meaning": "Authoritative for the submitted review text, star rating, product and this product's review history.",
        "content": json.dumps(facts, ensure_ascii=False),
    }]

    try:
        outcome = mcp_client.check_review_quality(
            review_text=review["review"],
            rating=review["rating"],
            existing_review_count=facts["existing_review_count"],
            average_rating=facts["average_rating"],
        )
        evidence.append({
            "id": "mcp_moderation",
            "source": "shared-mcp-check_review_quality",
            "status": "available",
            "meaning": "Validates spam and quality signals (flagged, reasons, spam_score, duplicate_risk) only. It does not itself decide whether to publish the review.",
            "content": json.dumps(outcome["result"], ensure_ascii=False),
        })
    except (mcp_client.MCPServiceUnavailable, mcp_client.MCPBadResponse) as exc:
        evidence.append({
            "id": "mcp_moderation",
            "source": "shared-mcp-check_review_quality",
            "status": "unavailable",
            "meaning": "Moderation signal was unavailable; this source does not decide whether to publish.",
            "content": "MCP moderation evidence is unavailable: {}".format(str(exc)[:300]),
        })

    return _call("POST", "/workflow", json={
        "subject_ref": _subject_ref(review["review_id"]),
        "request": {
            "goal": (
                "Assess whether this review should be published as-is, flagged for moderator "
                "attention, or rejected, using only the review's own text and rating and the "
                "moderation check result."
            ),
            "plan_contract": {
                "acceptance_criteria": [
                    "Identify the moderation signal in mcp_moderation (flagged, reasons, spam_score, duplicate_risk).",
                    "Check whether the review text and star rating are consistent with each other.",
                    "Call out evidence that is actually missing or unavailable; do not call supplied facts missing.",
                ],
                "constraints": [
                    "review_facts is authoritative for the submitted review text, rating and product.",
                    "mcp_moderation validates spam and quality signals only; it does not decide whether to publish.",
                    "Do not invent prior reviewer history or policy not present in the supplied evidence.",
                    "Do not publish, edit or delete the review yourself.",
                ],
            },
            "worker_evidence_ids": ["review_facts", "mcp_moderation"],
            "worker_required_evidence_ids": ["review_facts", "mcp_moderation"],
        },
        "evidence": evidence,
    })


def get_workflow(review_id, workflow_id):
    result = _call("GET", "/workflow/{}".format(workflow_id))
    if result.get("subject_ref") != _subject_ref(review_id):
        raise MultiAgentBadResponse("workflow does not belong to this review")
    return result


def list_workflows(review_id):
    return _call("GET", "/workflow/history", params={"subject_ref": _subject_ref(review_id)})


def review_workflow(review_id, workflow_id, payload):
    current = get_workflow(review_id, workflow_id)
    result = _call("POST", "/workflow/{}/review".format(workflow_id), json=payload)
    if result.get("subject_ref") != current.get("subject_ref"):
        raise MultiAgentBadResponse("workflow ownership changed during review")
    return result
