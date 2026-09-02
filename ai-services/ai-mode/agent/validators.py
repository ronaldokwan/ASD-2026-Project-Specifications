"""Guardrails used by the Observe step of the agentic loop.

A caller (any student backend) describes the JSON it expects with a small
schema; this module parses the LLM output and reports every violation so the
Adapt step can re-prompt with specific, actionable corrections.
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

        {"description": {"type": "string", "min_words": 25, "max_words": 60},
         "price":       {"type": "number", "min": 1, "max": 5000},
         "status":      {"type": "enum", "values": ["active", "draft"]}}
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
                # Tolerate "$1,299.00" style answers before rejecting them.
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
