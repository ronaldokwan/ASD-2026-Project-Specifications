"""Grounded loyalty reward suggestions through the shared AI-Mode service."""

import requests

from .config import Config


def _fallback(customer, reason):
    rewards = {
        "Bronze": "Free delivery on the next purchase",
        "Silver": "10% off the next purchase",
        "Gold": "15% off the next purchase or early access to a sale",
    }
    return {
        "ok": True,
        "result": {
            "reward": rewards.get(customer["loyalty_tier"], rewards["Bronze"]),
            "reason": (
                "A reliable {}-tier reward based on the customer's stored membership details."
            ).format(customer["loyalty_tier"]),
        },
        "attempts": 0,
        "fallback_used": True,
        "error": reason,
        "model": "deterministic fallback",
        "elapsed_ms": 0,
        "trace": [{
            "step": "Adapt",
            "status": "fallback",
            "detail": "AI-Mode was unavailable or returned an unusable result: {}".format(reason),
        }],
    }


def suggest_reward(customer):
    reward_options = {
        "Bronze": (
            "Free standard delivery on the next purchase",
            "Five percent off the next purchase",
        ),
        "Silver": (
            "Ten percent off the next purchase",
            "Free express delivery on the next purchase",
        ),
        "Gold": (
            "Fifteen percent off the next purchase",
            "Early access to the next seasonal sale",
        ),
    }
    options = reward_options.get(customer["loyalty_tier"], reward_options["Bronze"])
    reason_pattern = (
        "{} is currently a {}-tier customer, so this modest benefit matches the stored "
        "loyalty level."
    ).format(customer["name"], customer["loyalty_tier"])
    context = {
        "customer_name": customer["name"],
        "loyalty_tier": customer["loyalty_tier"],
        "joined_at": customer["joined_at"],
    }
    payload = {
        "goal": "customer_loyalty_reward",
        "task": (
            "Select exactly one of these approved rewards for the customer's stored tier and "
            "copy its wording exactly: '{}'; '{}'. For the reason, copy this grounded sentence "
            "exactly: '{}'. Do not add or imply any purchase, spending, order, preference, "
            "behaviour, demographic, or benefit-redemption history."
        ).format(options[0], options[1], reason_pattern),
        "context": context,
        "output_schema": {
            "reward": {
                "type": "string",
                "min_words": Config.REWARD_MIN_WORDS,
                "max_words": Config.REWARD_MAX_WORDS,
                "hint": (
                    "copy exactly one approved option: '{}' or '{}'"
                ).format(options[0], options[1]),
            },
            "reason": {
                "type": "string",
                "min_words": Config.REASON_MIN_WORDS,
                "max_words": Config.REASON_MAX_WORDS,
                "hint": (
                    "copy this sentence exactly: '{}'"
                ).format(reason_pattern),
            },
        },
        "fallback": _fallback(customer, "AI retry budget exhausted")["result"],
    }
    url = "{}/agent/run".format(Config.AI_MODE_URL)
    try:
        response = requests.post(url, json=payload, timeout=Config.AI_TIMEOUT)
        response.raise_for_status()
        outcome = response.json()
    except (requests.RequestException, ValueError) as exc:
        outcome = _fallback(customer, str(exc))

    if not isinstance(outcome.get("result"), dict):
        outcome = _fallback(customer, "AI-Mode returned no structured result")
    outcome["grounding"] = context
    return outcome


def ai_mode_health():
    try:
        response = requests.get("{}/health".format(Config.AI_MODE_URL), timeout=5)
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc)}
