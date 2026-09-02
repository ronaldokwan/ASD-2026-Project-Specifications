"""AI assistance for inventory restocking (POST /api/stock/recommend).

This module is the Inventory and Stock's half of the team's shared agentic
workflow. It does not call the LLM directly:

    frontend -> backend/API -> AI-Mode -> Ollama -> LLM

* **Plan**    - the backend gathers current low-stock items from the database
                microservice and provides their details for context.
* **Act**     - AI-Mode calls the approved open-source LLM to generate
                restock recommendations.
* **Observe** - AI-Mode validates the answer against the inventory guardrails
                (order quantity range, item selection).
* **Adapt**   - AI-Mode re-prompts with violations, and this module supplies
                a deterministic fallback for basic recommendations.
"""

import requests

from . import db_client
from .config import Config


class AIServiceError(RuntimeError):
    """The shared AI-Mode service could not be reached."""


# ----------------------------------------------------------------- Plan step
def build_context(category):
    """Gather low-stock items in the category for the recommendation prompt."""
    context = {
        "category": category,
        "currency": "AUD",
        "business": "Group 40 retail inventory",
    }

    try:
        low = db_client.list_low_stock()
        items_in_category = [item for item in low if item.get("category") == category]
    except db_client.DatabaseError:
        # Grounding is best-effort: a database blip must not disable the AI.
        context["low_stock_items"] = "unknown (low stock query unavailable)"
        return context

    if items_in_category:
        context["low_stock_count"] = len(items_in_category)
        context["low_stock_items"] = [
            {
                "sku": item.get("sku"),
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "restock_threshold": item.get("restock_threshold"),
                "location": item.get("location"),
            }
            for item in items_in_category
        ]
    else:
        context["low_stock_count"] = 0
        context["low_stock_items"] = []
        context["note"] = "No low-stock items in this category at the moment."

    return context


def _fallback(category, context):
    """Deterministic result used when the LLM cannot produce a valid answer."""
    items = context.get("low_stock_items", [])
    recommendations = []
    
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                qty = item.get("quantity", 0)
                threshold = item.get("restock_threshold", 50)
                order_qty = max(Config.RECOMMENDATION_MIN_ORDER, threshold * 2 - qty)
                order_qty = min(order_qty, Config.RECOMMENDATION_MAX_ORDER)
                
                recommendations.append({
                    "sku": item.get("sku", "UNKNOWN"),
                    "order_quantity": order_qty,
                    "reason": "Stock below threshold; recommend restocking to {} units".format(
                        threshold * 2),
                })
    
    return {"recommendations": recommendations}


# ------------------------------------------------------------- Act / Observe
def recommend_restocking(category):
    """Ask AI-Mode for restock recommendations for items in a category.

    Returns the AI-Mode envelope: result, attempts, fallback_used, model,
    elapsed_ms and the Plan/Act/Observe/Adapt trace shown in the UI.
    """
    context = build_context(category)
    fallback = _fallback(category, context)

    payload = {
        "goal": "inventory_restocking",
        "task": (
            "Provide specific restock order recommendations for items in the inventory that are "
            "below their restock threshold. For each item, suggest an order quantity that will "
            "bring stock levels to a comfortable level for sales. Consider current quantity, "
            "restock threshold, and typical demand patterns."
        ),
        "context": context,
        # These guardrails are the Observe step.
        "output_schema": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {
                            "type": "string",
                            "hint": "product SKU from context",
                        },
                        "order_quantity": {
                            "type": "integer",
                            "min": Config.RECOMMENDATION_MIN_ORDER,
                            "max": Config.RECOMMENDATION_MAX_ORDER,
                            "hint": "recommended number of units to order",
                        },
                        "reason": {
                            "type": "string",
                            "hint": "brief justification for the recommendation",
                        },
                    },
                    "required": ["sku", "order_quantity", "reason"],
                },
                "hint": "array of restock recommendations, one per low-stock item",
            },
        },
        "fallback": fallback,
    }

    url = "{}/agent/run".format(Config.AI_MODE_URL)
    try:
        response = requests.post(url, json=payload, timeout=Config.AI_TIMEOUT)
    except requests.RequestException as exc:
        raise AIServiceError("AI-Mode unreachable at {}: {}".format(url, exc)) from exc

    if response.status_code >= 500 and not response.content:
        raise AIServiceError("AI-Mode returned {} with no body".format(response.status_code))

    try:
        outcome = response.json()
    except ValueError as exc:
        raise AIServiceError("AI-Mode returned a non-JSON response") from exc

    # If AI-Mode itself failed, still hand the UI something usable.
    if not outcome.get("result"):
        outcome["result"] = fallback
        outcome["fallback_used"] = True

    outcome["grounding"] = context
    return outcome


def ai_mode_health():
    try:
        response = requests.get("{}/health".format(Config.AI_MODE_URL), timeout=5)
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
