"""AI assistance for the Product Catalogue (POST /api/products/ai).

This module is the Product Catalogue's half of the team's shared agentic
workflow. It does not call the LLM directly:

    frontend -> backend/API -> AI-Mode -> Ollama -> LLM

* **Plan**    - the backend grounds the request by pulling real facts out of its
                own database microservice (how many products the category has,
                its average / minimum / maximum price, sample products).
* **Act**     - AI-Mode calls the approved open-source LLM.
* **Observe** - AI-Mode validates the answer against the catalogue guardrails
                declared below (word count, price range).
* **Adapt**   - AI-Mode re-prompts with the violations, and this module supplies
                a deterministic fallback so the catalogue UI always gets copy.
"""

import requests

from . import db_client
from .config import Config

DEFAULT_PRICE = 49.95


class AIServiceError(RuntimeError):
    """The shared AI-Mode service could not be reached."""


# ----------------------------------------------------------------- Plan step
def build_context(name, category, keywords=""):
    """Gather grounding facts for the prompt from the database microservice."""
    context = {
        "product_name": name,
        "category": category,
        "currency": "AUD",
        "seller": "Group 40 retail store",
    }
    if keywords:
        context["seller_keywords"] = keywords

    try:
        stats = db_client.category_stats(category)
    except db_client.DatabaseError:
        # Grounding is best-effort: a database blip must not disable the AI.
        context["category_products"] = "unknown (catalogue statistics unavailable)"
        return context

    if stats.get("product_count"):
        context["category_products"] = stats["product_count"]
        context["category_avg_price"] = stats.get("avg_price")
        context["category_price_range"] = "{} to {}".format(
            stats.get("min_price"), stats.get("max_price"))
        context["comparable_products"] = ", ".join(
            "{} at ${}".format(item["name"], item["price"]) for item in stats.get("sample", [])
        ) or "none"
    else:
        context["category_products"] = 0
        context["note"] = "This is the first product in this category."

    return context


def _fallback(name, category, context):
    """Deterministic result used when the LLM cannot produce a valid answer."""
    price = context.get("category_avg_price") or DEFAULT_PRICE
    description = (
        "{name} is a {category_lower} product in the Group 40 catalogue. "
        "This description was generated locally because the AI model could not be reached, "
        "so please review the wording and the suggested price before publishing the product."
    ).format(name=name, category_lower=category.lower())
    return {"description": description, "price": round(float(price), 2)}


# ------------------------------------------------------------- Act / Observe
def suggest_product_copy(name, category, keywords=""):
    """Ask AI-Mode for a description and a price suggestion for one product.

    Returns the AI-Mode envelope: result, attempts, fallback_used, model,
    elapsed_ms and the Plan/Act/Observe/Adapt trace shown in the UI.
    """
    context = build_context(name, category, keywords)
    fallback = _fallback(name, category, context)

    payload = {
        "goal": "product_catalogue_copy",
        "task": (
            "Write marketing copy and a competitive retail price for a product that is about to "
            "be listed in an online store. Keep the tone factual and concise, mention what the "
            "product is and who it suits, and price it sensibly against the comparable products "
            "in the context."
        ),
        "context": context,
        # These guardrails are the Observe step.
        "output_schema": {
            "description": {
                "type": "string",
                "min_words": Config.DESCRIPTION_MIN_WORDS,
                "max_words": Config.DESCRIPTION_MAX_WORDS,
                "hint": "one paragraph of retail copy, no bullet points",
            },
            "price": {
                "type": "number",
                "min": Config.PRICE_MIN,
                "max": Config.PRICE_MAX,
                "hint": "retail price in AUD",
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
