"""Guardrails used by the Observe step of the agentic loop.

A caller (any student backend) describes the JSON it expects with a small
schema; this module parses the LLM output and reports every violation so the
Adapt step can re-prompt with specific, actionable corrections.
"""

import json
import re

# Canned Observe schemas for the two Release 1 validation modes (see
# app.py: POST /agent/validate). Both ask the model to check somebody else's
# already-produced output (an MCP tool result, or a RAG answer + citations)
# rather than to generate anything new.
MCP_VALIDATION_SCHEMA = {
    "valid": {
        "type": "enum",
        "values": ["true", "false"],
        "hint": "true only when the supplied tool result is internally consistent",
    },
    "notes": {
        "type": "string", "min_words": 1, "max_words": 60,
        "hint": "identify an actual contract problem when invalid; do not invent issues",
    },
    "confidence": {"type": "enum", "values": ["high", "medium", "low"]},
}

RAG_VALIDATION_SCHEMA = {
    "grounded": {
        "type": "enum",
        "values": ["true", "false"],
        "hint": "true only when every answer claim is supported by the sources",
    },
    "unsupported_claims": {
        "type": "string", "min_words": 1, "max_words": 60,
        "hint": "exactly 'none' when grounded is true; otherwise identify the unsupported claims",
    },
    "confidence_ok": {"type": "enum", "values": ["true", "false"]},
}


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


def _reported_items(value):
    """Return non-empty error/warning values as displayable text."""
    if value in (None, False, "", [], {}):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [
            "{}: {}".format(key, item)
            for key, item in value.items()
            if item not in (None, False, "", [], {})
        ]
    return [str(value).strip()]


def validate_mcp_verdict(data, subject):
    """Make an MCP verdict agree with the supplied structured tool result.

    Registered tools can have different domain-specific output schemas, so the
    model still judges their semantics. This guardrail handles facts common to
    every MCP call: a named tool, a structured result, matching tool identity,
    and explicit error indicators. For a valid result, the explanatory note is
    derived from those facts instead of accepting speculative model prose.
    """
    cleaned = dict(data)
    subject_data = subject if isinstance(subject, dict) else {}
    tool_name = subject_data.get("tool") or subject_data.get("tool_name")
    result = subject_data.get("result")
    problems = []

    if not isinstance(tool_name, str) or not tool_name.strip():
        problems.append("the registered tool name is missing")
    if not isinstance(result, dict) or not result:
        problems.append("the tool result is not a non-empty structured object")
    else:
        result_tool = result.get("tool")
        if (
            isinstance(result_tool, str)
            and isinstance(tool_name, str)
            and result_tool.strip() != tool_name.strip()
        ):
            problems.append(
                "the result identifies tool '{}' instead of '{}'".format(
                    result_tool.strip(), tool_name.strip()
                )
            )
        for field in ("error", "errors"):
            problems.extend(_reported_items(result.get(field)))
        if result.get("is_error") is True:
            problems.append("the tool result is marked as an error")
        if result.get("ok") is False:
            problems.append("the tool result reports ok=false")

    if problems:
        cleaned["valid"] = "false"
        cleaned["notes"] = "The tool result is invalid: {}.".format(
            "; ".join(problem.rstrip(". ") for problem in problems)
        )
    elif cleaned.get("valid") == "true":
        warnings = _reported_items(result.get("warnings"))
        cleaned["notes"] = (
            "The registered MCP tool returned a structured result with no reported errors."
        )
        if warnings:
            cleaned["notes"] += " Reported warnings: {}.".format(
                "; ".join(warning.rstrip(". ") for warning in warnings)
            )
    return cleaned, []


def _normalise_evidence(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _answer_is_verbatim_supported(subject):
    """Recognise the strongest generic grounding case without an LLM judgment.

    The shared RAG service deliberately returns extractive answers when a model
    paraphrase cannot be verified. Each answer sentence must therefore occur in
    at least one supplied source excerpt before this shortcut can mark it as
    supported. Answers without direct support are handled conservatively by the
    verdict guardrail below.
    """
    if not isinstance(subject, dict):
        return False
    answer = subject.get("answer")
    sources = subject.get("sources")
    if not isinstance(answer, str) or not answer.strip() or not isinstance(sources, list):
        return False

    evidence = []
    for source in sources:
        if isinstance(source, str):
            text = source
        elif isinstance(source, dict):
            text = " ".join(
                str(source.get(field) or "")
                for field in ("snippet", "text", "content", "excerpt")
            )
        else:
            continue
        normalised = _normalise_evidence(text)
        if normalised:
            evidence.append(normalised)
    if not evidence:
        return False

    claims = [
        _normalise_evidence(claim)
        for claim in re.split(r"(?<=[.!?])\s+", answer.strip())
        if _normalise_evidence(claim)
    ]
    return bool(claims) and all(
        any(claim in source_text for source_text in evidence)
        for claim in claims
    )


def validate_rag_verdict(data, subject):
    """Enforce a coherent RAG verdict and construct its explanation.

    The LLM proposes a verdict, while this guardrail independently recognises
    exact extractive support and rejects an unverified positive verdict. It also
    enforces the relationship between the final verdict and unsupported claims.
    Notes are derived from the accepted structured fields, so they cannot state
    the opposite conclusion.
    """
    cleaned = dict(data)
    verbatim_supported = _answer_is_verbatim_supported(subject)
    if verbatim_supported:
        cleaned["grounded"] = "true"
        cleaned["unsupported_claims"] = "none"

    subject_data = subject if isinstance(subject, dict) else {}
    sources = subject_data.get("sources")
    confidence = str(subject_data.get("confidence") or "").strip().casefold()
    if isinstance(sources, list) and confidence in ("high", "medium", "low"):
        expected_confidence = "high" if len(sources) >= 3 else (
            "medium" if sources else "low"
        )
        cleaned["confidence_ok"] = str(
            confidence == expected_confidence
        ).lower()

    grounded = cleaned.get("grounded")
    unsupported = str(cleaned.get("unsupported_claims") or "").strip()
    means_none = re.sub(r"[^a-z]", "", unsupported.casefold()) == "none"
    violations = []

    if grounded == "true" and means_none and not verbatim_supported:
        cleaned["grounded"] = "false"
        cleaned["unsupported_claims"] = (
            "The answer is not directly supported by the supplied source excerpts."
        )
        grounded = "false"
        unsupported = cleaned["unsupported_claims"]
        means_none = False

    if grounded == "true" and not means_none:
        violations.append(
            "'unsupported_claims' must be 'none' when 'grounded' is true"
        )
    elif grounded == "false" and means_none:
        violations.append(
            "'unsupported_claims' must identify the problem when 'grounded' is false"
        )

    if grounded == "true":
        if (
            not isinstance(subject_data.get("answer"), str)
            or not subject_data["answer"].strip()
        ):
            violations.append("a grounded verdict requires a non-empty answer")
        if not isinstance(sources, list) or not sources:
            violations.append("a grounded verdict requires at least one source")

    if violations:
        return cleaned, violations

    if grounded == "true":
        cleaned["unsupported_claims"] = "none"
        cleaned["notes"] = "The answer is supported by the retrieved evidence."
    else:
        problem = unsupported.rstrip(". ")
        cleaned["notes"] = (
            "The answer is not fully supported by the retrieved evidence. "
            "Unsupported claims: {}.".format(problem)
        )
    return cleaned, []
