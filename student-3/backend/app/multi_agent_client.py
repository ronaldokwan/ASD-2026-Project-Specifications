"""Student 3 adapter for the shared loyalty recommendation workflow."""

import json

import requests

from . import mcp_client, rag_client
from .config import Config


class MultiAgentUnavailable(RuntimeError):
    """The shared Multi-Agent service is disabled or unreachable."""


class MultiAgentBadResponse(RuntimeError):
    """The shared Multi-Agent service returned an invalid response."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


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


def start_loyalty_review(customer):
    if not Config.MULTI_AGENT_ENABLED:
        raise MultiAgentUnavailable("Multi-Agent integration is disabled")

    facts = {
        "loyalty_tier": customer.get("loyalty_tier"),
        "joined_at": customer.get("joined_at"),
        "has_phone": bool(customer.get("phone")),
        "has_address": bool(customer.get("address")),
    }
    evidence = [{
        "id": "customer_facts",
        "source": "student-3-customer-api",
        "status": "available",
        "meaning": "Authoritative for this customer's stored loyalty_tier, joined_at, and whether optional phone/address fields are present.",
        "content": json.dumps(facts, ensure_ascii=False),
    }]

    try:
        profile = mcp_client.check_customer_profile(customer)
        evidence.append({
            "id": "mcp_profile",
            "source": "shared-mcp-check_customer_profile",
            "status": "available",
            "meaning": "Validates profile completeness and whether the stored tier is valid. It does not define or authorize loyalty benefits.",
            "content": json.dumps(profile, ensure_ascii=False),
        })
    except (mcp_client.MCPServiceUnavailable, mcp_client.MCPBadResponse) as exc:
        evidence.append({
            "id": "mcp_profile",
            "source": "shared-mcp-check_customer_profile",
            "status": "unavailable",
            "meaning": "Profile validation was unavailable; this source does not define or authorize loyalty benefits.",
            "content": "MCP profile evidence is unavailable: {}".format(str(exc)[:300]),
        })

    try:
        policy = rag_client.ask_loyalty_benefits(
            "What loyalty benefits are approved for a {} customer?".format(facts["loyalty_tier"])
        )
        matching_section = "{} Membership".format(facts["loyalty_tier"])
        matching_policy = policy.get("status") == "ok" and any(
            source.get("section") == matching_section
            for source in policy.get("sources", []) if isinstance(source, dict)
        )
        evidence.append({
            "id": "loyalty_policy",
            "source": "shared-rag-customer-loyalty-policy",
            "status": "available" if matching_policy else "insufficient",
            "meaning": "Authoritative policy evidence for approved benefits only when its source section matches the customer's stored tier.",
            "content": json.dumps(policy, ensure_ascii=False),
        })
    except (rag_client.RAGServiceUnavailable, rag_client.RAGBadResponse) as exc:
        evidence.append({
            "id": "loyalty_policy",
            "source": "shared-rag-customer-loyalty-policy",
            "status": "unavailable",
            "meaning": "Approved benefit policy could not be retrieved and must not be inferred.",
            "content": "Loyalty policy evidence is unavailable: {}".format(str(exc)[:300]),
        })

    return _call("POST", "/workflow", json={
        "subject_ref": "student-3-customer:{}".format(customer["id"]),
        "request": {
            "goal": "Summarize the approved benefit options for the customer's stored tier for human review.",
            "plan_contract": {
                "acceptance_criteria": [
                    "Identify the tier recorded in customer_facts.",
                    "Use only benefits stated in loyalty_policy for that same tier.",
                    "Call out evidence that is actually missing or unavailable; do not call supplied facts missing.",
                ],
                "constraints": [
                    "customer_facts is authoritative for stored customer fields.",
                    "mcp_profile validates profile completeness and tier validity; it is not reward policy.",
                    "Phone and address are optional and do not establish tier or reward eligibility.",
                    "Do not infer purchase history, eligibility, or authorization, and do not change the customer or apply a reward.",
                ],
            },
            "worker_evidence_ids": ["customer_facts", "loyalty_policy"],
            "worker_required_evidence_ids": ["customer_facts", "loyalty_policy"],
            "worker_policy_evidence_ids": ["loyalty_policy"],
        },
        "evidence": evidence,
    })


def get_workflow(customer_id, workflow_id):
    result = _call("GET", "/workflow/{}".format(workflow_id))
    if result.get("subject_ref") != "student-3-customer:{}".format(customer_id):
        raise MultiAgentBadResponse("workflow does not belong to this customer")
    return result


def list_workflows(customer_id):
    return _call("GET", "/workflow/history", params={
        "subject_ref": "student-3-customer:{}".format(customer_id),
    })


def review_workflow(customer_id, workflow_id, payload):
    current = get_workflow(customer_id, workflow_id)
    result = _call("POST", "/workflow/{}/review".format(workflow_id), json=payload)
    if result.get("subject_ref") != current.get("subject_ref"):
        raise MultiAgentBadResponse("workflow ownership changed during review")
    return result
