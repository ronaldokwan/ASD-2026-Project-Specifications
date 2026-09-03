"""AI assistance for Reviews and Ratings (POST /api/reviews/ai).

This module is the Reviews and Ratings feature's half of the team's shared
agentic workflow. It does not call the LLM directly:

    frontend -> backend/API -> AI-Mode -> Ollama -> LLM

* **Plan**    - the backend grounds the request by pulling real facts out of its
                own database microservice: how many reviews the product has,
                its average rating, the rating distribution, and a sample of
                the highest- and lowest-rated review text.
* **Act**     - AI-Mode calls the approved open-source LLM.
* **Observe** - AI-Mode validates the answer against the guardrails declared
                below (a one-line summary plus pros and cons, each within a
                word budget).
* **Adapt**   - AI-Mode re-prompts with the violations, and this module supplies
                a deterministic fallback so the product page always gets a
                summary, even with no reviews or an unreachable LLM.
"""

import requests

from . import db_client
from .config import Config


class AIServiceError(RuntimeError):
    """The shared AI-Mode service could not be reached."""


# ----------------------------------------------------------------- Plan step
def build_context(product_sku, product_name=None):
    """Gather grounding facts for the prompt from the database microservice."""
    context = {"product_sku": product_sku}
    if product_name and product_name != product_sku:
        context["product_name"] = product_name

    try:
        stats = db_client.product_stats(product_sku)
    except db_client.DatabaseError:
        # Grounding is best-effort: a database blip must not disable the AI.
        context["review_count"] = "unknown (review statistics unavailable)"
        return context

    context["review_count"] = stats.get("review_count", 0)
    if context["review_count"]:
        context["average_rating"] = stats.get("avg_rating")
        context["rating_distribution"] = stats.get("rating_distribution", {})
        context["review_excerpts"] = "; ".join(
            "{} stars - \"{}\"".format(item["rating"], item["review"])
            for item in stats.get("sample", [])
        ) or "none"
    else:
        context["note"] = "This product has no reviews yet."

    return context


def _fallback(context):
    """Deterministic result used when the LLM cannot produce a valid answer."""
    count = context.get("review_count") or 0
    if not count or not isinstance(count, int):
        return {
            "summary": "This product has no reviews yet, so there is nothing to summarise.",
            "pros": "Not enough data yet.",
            "cons": "Not enough data yet.",
        }

    average = context.get("average_rating") or 0
    distribution = context.get("rating_distribution", {})
    high = int(distribution.get("5", 0)) + int(distribution.get("4", 0))
    low = int(distribution.get("1", 0)) + int(distribution.get("2", 0))

    summary = (
        "This summary was generated locally because the AI model could not be reached. "
        "Average rating is {average} from {count} review(s); please read the reviews below."
    ).format(average=average, count=count)
    pros = (
        "{high} review(s) rated 4 or 5 stars - see the highest-rated reviews below for details."
        .format(high=high) if high else "No consistently positive themes were found yet."
    )
    cons = (
        "{low} review(s) rated 1 or 2 stars - see the lowest-rated reviews below for details."
        .format(low=low) if low else "No consistently negative themes were found yet."
    )
    return {"summary": summary, "pros": pros, "cons": cons}


# ------------------------------------------------------------- Act / Observe
def summarise_reviews(product_sku, product_name=None):
    """Ask AI-Mode to summarise one product's reviews into pros and cons.

    Returns the AI-Mode envelope: result, attempts, fallback_used, model,
    elapsed_ms and the Plan/Act/Observe/Adapt trace shown in the UI.
    """
    context = build_context(product_sku, product_name)
    fallback = _fallback(context)

    payload = {
        "goal": "review_pros_cons_summary",
        "task": (
            "Read the customer reviews summarised in the context and write a short, factual "
            "summary of what reviewers think of this product, then list its pros and its cons "
            "as separate short phrases separated by semicolons. Only mention things the reviews "
            "actually say; do not invent details."
        ),
        "context": context,
        # These guardrails are the Observe step.
        "output_schema": {
            "summary": {
                "type": "string",
                "min_words": Config.SUMMARY_MIN_WORDS,
                "max_words": Config.SUMMARY_MAX_WORDS,
                "hint": "one or two sentences, no bullet points",
            },
            "pros": {
                "type": "string",
                "min_words": 3,
                "max_words": Config.SUMMARY_MAX_WORDS,
                "hint": "short phrases separated by semicolons",
            },
            "cons": {
                "type": "string",
                "min_words": 3,
                "max_words": Config.SUMMARY_MAX_WORDS,
                "hint": "short phrases separated by semicolons; write 'None noted' if there are none",
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
