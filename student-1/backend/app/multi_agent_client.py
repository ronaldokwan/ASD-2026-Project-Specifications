"""Client for the shared Multi-Agent server - the listing readiness review.

frontend -> backend/API -> shared Multi-Agent server (/workflow)
         -> Planner -> Worker -> Reviewer -> human review (administrator)

The backend gathers the evidence (stored product fields, the shared MCP listing
check and the RAG catalogue policy) so the agents only ever reason over
supplied, citable sources. The administrator's decision is recorded on the
workflow; it never edits or publishes the product.
"""

import json
import re

import requests

from . import mcp_client, rag_client
from .config import Config

_POLICY_QUESTION = (
    "When is a product listing ready to publish, and which category, price and "
    "status rules apply?"
)


class MultiAgentUnavailable(RuntimeError):
    """The shared Multi-Agent server is disabled or unreachable."""


class MultiAgentBadResponse(RuntimeError):
    """The Multi-Agent server rejected the request or returned bad data."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def subject_ref(product_id):
    return "{}:{}".format(Config.MULTI_AGENT_SUBJECT, product_id)


def _call(method, path, **kwargs):
    url = Config.MULTI_AGENT_URL + path
    try:
        response = requests.request(
            method, url, timeout=Config.MULTI_AGENT_TIMEOUT, **kwargs
        )
    except requests.RequestException as exc:
        raise MultiAgentUnavailable(
            "Multi-Agent server is unreachable at {}".format(Config.MULTI_AGENT_URL)
        ) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise MultiAgentBadResponse("Multi-Agent server returned non-JSON data") from exc
    if response.status_code >= 500:
        raise MultiAgentUnavailable(
            body.get("error", "Multi-Agent server is unavailable")
        )
    if response.status_code >= 400:
        raise MultiAgentBadResponse(
            body.get("error", "workflow request was rejected"),
            status=response.status_code,
        )
    return body


# ------------------------------------------------------------------ evidence
def readiness_checks(product):
    """The Listing Readiness rule, checked deterministically by the application.

    Small models miscount words and misread ranges, so the agents are given
    the result of each rule rather than asked to work it out.
    """
    price = float(product["price"])
    words = len((product.get("description") or "").split())
    return {
        "status_is_active": product["status"] == "active",
        "category_is_valid": product["category"] in Config.VALID_CATEGORIES,
        "price_within_1_to_9999_aud": Config.PRICE_MIN <= price <= Config.PRICE_MAX,
        "description_has_at_least_8_words": words >= Config.READINESS_MIN_DESCRIPTION_WORDS,
    }


def _product_facts(product):
    description = (product.get("description") or "").strip()
    checks = readiness_checks(product)
    facts = {
        "sku": product["sku"],
        "name": product["name"],
        "category": product["category"],
        "price_aud": float(product["price"]),
        "status": product["status"],
        "description_word_count": len(description.split()),
        "description": description,
        "readiness_checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    return {
        "id": "product_facts",
        "source": "student-1-product-api",
        "status": "available",
        "meaning": "Authoritative stored product fields. readiness_checks is the application's "
        "exact check of each Listing Readiness rule; failed_checks lists the rules not met.",
        "content": json.dumps(facts, ensure_ascii=False),
    }


# The MCP price comparison is market context, not a readiness rule; left out
# because models read "below_range" as a policy breach.
_MCP_FIELDS = ("tool", "sku", "listing_status", "description_word_count",
               "issues", "warnings", "errors")


def _mcp_evidence(product):
    meaning = (
        "Independent cross-check from the shared MCP listing tool: listing_status and any "
        "issues, warnings or errors. Validation evidence, not policy."
    )
    try:
        outcome = mcp_client.check_listing(product)
    except (mcp_client.MCPServiceUnavailable, mcp_client.MCPBadResponse) as exc:
        return {
            "id": "mcp_listing",
            "source": "shared-mcp-check_product_listing",
            "status": "unavailable",
            "meaning": meaning,
            "content": "MCP listing check is unavailable: {}".format(str(exc)[:300]),
        }
    return {
        "id": "mcp_listing",
        "source": "shared-mcp-check_product_listing",
        "status": "available",
        "meaning": meaning,
        "content": json.dumps(
            {key: outcome["result"][key] for key in _MCP_FIELDS if key in outcome["result"]},
            ensure_ascii=False,
        ),
    }


def _policy_evidence():
    meaning = (
        "Catalogue policy retrieved by the shared RAG server. Authoritative for "
        "listing readiness only when a Listing Readiness section is cited."
    )
    try:
        policy = rag_client.ask(_POLICY_QUESTION)
    except (rag_client.RAGServiceUnavailable, rag_client.RAGBadResponse) as exc:
        return {
            "id": "catalogue_policy",
            "source": "shared-rag-product-catalogue-policy",
            "status": "unavailable",
            "meaning": meaning,
            "content": "Catalogue policy is unavailable: {}".format(str(exc)[:300]),
        }
    cites_readiness = policy["status"] == "ok" and any(
        Config.READINESS_SECTION in source["section"] for source in policy["sources"]
    )
    return {
        "id": "catalogue_policy",
        "source": "shared-rag-product-catalogue-policy",
        "status": "available" if cites_readiness else "insufficient",
        "meaning": meaning,
        "content": json.dumps(policy, ensure_ascii=False)[:8000],
    }


def build_request(product):
    """The /workflow payload: goal, application-enforced contract and evidence."""
    return {
        "subject_ref": subject_ref(product["id"]),
        "request": {
            "goal": "Say whether this product listing is ready to publish under the catalogue "
            "policy, for administrator review. It is ready only if failed_checks in "
            "product_facts is empty; otherwise name each failed check as the fix. Write the "
            "recommendation as one sentence and the rationale as one short sentence.",
            "plan_contract": {
                "acceptance_criteria": [
                    "Base readiness on readiness_checks and failed_checks in product_facts.",
                    "Cite catalogue_policy as the source of the readiness rules.",
                    "Name every failed check as a fix, or state that none failed.",
                ],
                "constraints": [
                    "product_facts is authoritative for stored product fields and rule results.",
                    "mcp_listing is an independent cross-check; it does not define catalogue policy.",
                    "Do not invent prices, stock, sales or competitor data.",
                    "Do not edit, publish, archive or delete the product.",
                ],
            },
            "worker_evidence_ids": ["product_facts", "catalogue_policy"],
            "worker_required_evidence_ids": ["product_facts", "catalogue_policy"],
            "worker_policy_evidence_ids": ["catalogue_policy"],
        },
        "evidence": [
            _product_facts(product),
            _mcp_evidence(product),
            _policy_evidence(),
        ],
    }


# ---------------------------------------------------------------------- public
def start_listing_review(product):
    """Queue a Planner -> Worker -> Reviewer workflow for one product."""
    if not Config.MULTI_AGENT_ENABLED:
        raise MultiAgentUnavailable("Multi-Agent integration is disabled")
    return _call("POST", "/workflow", json=build_request(product))


def application_check(workflow):
    """Compare the Worker's ready / not-ready verdict with the deterministic rule result.

    Readiness is fully decided by failed_checks, so the application can check the
    Worker itself instead of relying only on the Reviewer model.
    """
    worker = workflow.get("worker_result") or {}
    facts = next((item for item in workflow.get("evidence") or []
                  if item.get("id") == "product_facts"), None)
    if not worker.get("recommendation") or facts is None:
        return None
    try:
        failed = json.loads(facts["content"]).get("failed_checks")
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(failed, list):
        return None

    text = worker["recommendation"].lower()
    if re.search(r"\bnot\s+(?:yet\s+)?ready\b|\bunready\b", text):
        verdict = "not ready"
    elif re.search(r"\bready\b", text):
        verdict = "ready"
    else:
        verdict = None
    expected = "not ready" if failed else "ready"
    return {
        "expected": expected,
        "failed_checks": failed,
        "worker_verdict": verdict,
        "agrees": None if verdict is None else verdict == expected,
    }


def _with_check(workflow):
    workflow["application_check"] = application_check(workflow)
    return workflow


def get_workflow(product_id, workflow_id):
    result = _call("GET", "/workflow/{}".format(workflow_id))
    if result.get("subject_ref") != subject_ref(product_id):
        raise MultiAgentBadResponse("workflow does not belong to this product", 404)
    return _with_check(result)


def list_workflows(product_id):
    return _call(
        "GET", "/workflow/history", params={"subject_ref": subject_ref(product_id)}
    )


def review_workflow(product_id, workflow_id, payload):
    """Record the administrator's accept / partial_accept / reject decision."""
    get_workflow(product_id, workflow_id)
    return _with_check(
        _call("POST", "/workflow/{}/review".format(workflow_id), json=payload)
    )


def health():
    if not Config.MULTI_AGENT_ENABLED:
        return {"status": "disabled"}
    try:
        response = requests.get(
            "{}/health".format(Config.MULTI_AGENT_URL), timeout=(1, 3)
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
