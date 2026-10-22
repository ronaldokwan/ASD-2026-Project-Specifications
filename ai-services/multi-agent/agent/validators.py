"""Guardrails used by the Planner, Worker and Reviewer agents.

Mirrors the scalar field types in ai-services/ai-mode/agent/validators.py
(string / number / integer / enum), plus one addition: a "list" type for the
short ordered lists the Planner (steps) and Reviewer (risks) produce.
"""

import json
import re


def parse_json(raw):
    """Best-effort JSON parse of an LLM response.

    Small open-source models occasionally wrap JSON in prose or code fences,
    so fall back to extracting the outermost object before giving up.
    """
    if not raw:
        raise ValueError("model returned an empty response")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not match:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(match.group(0))


def _word_count(text):
    return len([w for w in re.split(r"\s+", str(text).strip()) if w])


def validate(data, schema):
    """Validate ``data`` against ``schema``; return (cleaned, violations).

    Schema example::

        {"steps":  {"type": "list", "min_items": 2, "max_items": 5, "item_max_words": 20},
         "verdict": {"type": "enum", "values": ["approve", "revise", "reject"]},
         "summary": {"type": "string", "min_words": 3, "max_words": 40}}
    """
    violations = []
    cleaned = {}

    if not isinstance(data, dict):
        return {}, ["response must be a JSON object"]

    for field, rules in schema.items():
        required = rules.get("required", True)
        if field not in data or data[field] in (None, ""):
            if required:
                violations.append(f"'{field}' is missing")
            continue

        value = data[field]
        kind = rules.get("type", "string")

        if kind in ("number", "integer"):
            try:
                value = float(str(value).replace("$", "").replace(",", "").strip())
            except (TypeError, ValueError):
                violations.append(f"'{field}' must be a number, got {value!r}")
                continue
            if kind == "integer":
                value = int(round(value))
            if "min" in rules and value < rules["min"]:
                violations.append(f"'{field}' must be >= {rules['min']}, got {value}")
                continue
            if "max" in rules and value > rules["max"]:
                violations.append(f"'{field}' must be <= {rules['max']}, got {value}")
                continue
            cleaned[field] = round(value, 2) if kind == "number" else value

        elif kind == "enum":
            allowed = rules.get("values", [])
            text = str(value).strip().lower()
            if text not in [str(a).lower() for a in allowed]:
                violations.append(f"'{field}' must be one of {allowed}, got {value!r}")
                continue
            cleaned[field] = text

        elif kind == "list":
            if not isinstance(value, list):
                violations.append(f"'{field}' must be a list")
                continue
            items = [str(item).strip() for item in value if str(item).strip()]
            min_items = rules.get("min_items", 0)
            if len(items) < min_items:
                violations.append(f"'{field}' must have at least {min_items} item(s)")
                continue
            items = items[: rules.get("max_items", 10)]
            item_max_words = rules.get("item_max_words")
            if item_max_words and any(_word_count(i) > item_max_words for i in items):
                violations.append(
                    f"'{field}' items must be at most {item_max_words} words each"
                )
                continue
            cleaned[field] = items

        else:  # string
            text = str(value).strip()
            words = _word_count(text)
            if "min_words" in rules and words < rules["min_words"]:
                violations.append(
                    f"'{field}' is {words} words, must be at least {rules['min_words']}"
                )
                continue
            if "max_words" in rules and words > rules["max_words"]:
                violations.append(
                    f"'{field}' is {words} words, must be at most {rules['max_words']}"
                )
                continue
            if "max_chars" in rules and len(text) > rules["max_chars"]:
                violations.append(f"'{field}' is longer than {rules['max_chars']} characters")
                continue
            cleaned[field] = text

    return cleaned, violations
