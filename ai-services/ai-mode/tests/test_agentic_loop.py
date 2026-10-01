"""Unit tests for the shared agentic loop.

The LLM is replaced by a stub client so the tests run offline in GitHub Actions
(no Ollama container in CI).

Run from the repository root:  pytest ai-services/ai-mode/tests -v
"""

import os
import sys

import pytest

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from agent.loop import AgenticLoop, AgentRequest  # noqa: E402
from agent.ollama_client import OllamaError  # noqa: E402
from agent.validators import (  # noqa: E402
    MCP_VALIDATION_SCHEMA,
    RAG_VALIDATION_SCHEMA,
    parse_json,
    validate,
)


class StubClient:
    """Returns canned answers in order; records the prompts it was given."""

    model = "stub-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, system=None, json_mode=True, temperature=0.4):
        self.prompts.append(prompt)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


SCHEMA = {
    "description": {"type": "string", "min_words": 3, "max_words": 40},
    "price": {"type": "number", "min": 1, "max": 100},
}


def make_request(**overrides):
    payload = {
        "goal": "product_copy",
        "task": "Write a product description and suggest a price.",
        "context": {"category": "Accessories", "category_avg_price": 25.0},
        "output_schema": SCHEMA,
        "fallback": {"description": "Fallback copy for this product.", "price": 25.0},
    }
    payload.update(overrides)
    return AgentRequest.from_json(payload)


# --------------------------------------------------------------- validators
def test_parse_json_handles_code_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_extracts_object_from_prose():
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_validate_coerces_currency_string():
    cleaned, violations = validate({"description": "a b c", "price": "$42.50"}, SCHEMA)
    assert violations == []
    assert cleaned["price"] == 42.5


def test_validate_reports_every_violation():
    _, violations = validate({"description": "short", "price": 5000}, SCHEMA)
    assert len(violations) == 2


# --------------------------------------------------------------------- loop
def test_loop_succeeds_on_first_attempt():
    client = StubClient(['{"description": "A neat little thing.", "price": 19.99}'])
    outcome = AgenticLoop(client=client, max_attempts=2).run(make_request())

    assert outcome["ok"] is True
    assert outcome["fallback_used"] is False
    assert outcome["attempts"] == 1
    assert outcome["result"]["price"] == 19.99
    assert [s["step"] for s in outcome["trace"]] == ["Plan", "Act", "Observe"]


def test_loop_adapts_after_a_rejected_answer():
    client = StubClient([
        '{"description": "too short", "price": 999}',        # violates both rules
        '{"description": "A neat little thing.", "price": 19.99}',
    ])
    outcome = AgenticLoop(client=client, max_attempts=2).run(make_request())

    assert outcome["ok"] is True
    assert outcome["attempts"] == 2
    assert "Adapt" in [s["step"] for s in outcome["trace"]]
    # The Adapt prompt must tell the model exactly what was wrong.
    assert "rejected" in client.prompts[1]


def test_loop_falls_back_when_every_attempt_fails():
    client = StubClient(["not json at all", "still not json"])
    outcome = AgenticLoop(client=client, max_attempts=2).run(make_request())

    assert outcome["fallback_used"] is True
    assert outcome["result"]["price"] == 25.0
    assert outcome["trace"][-1]["status"] == "fallback"


def test_loop_falls_back_when_ollama_is_unreachable():
    client = StubClient([OllamaError("connection refused")])
    outcome = AgenticLoop(client=client, max_attempts=2).run(make_request())

    assert outcome["fallback_used"] is True
    assert "connection refused" in outcome["error"]


def test_plan_includes_context_facts():
    prompt = AgenticLoop(client=StubClient([]), max_attempts=1).plan(make_request())
    assert "category_avg_price: 25.0" in prompt
    assert "description" in prompt and "price" in prompt


def test_request_requires_task_and_schema():
    with pytest.raises(ValueError):
        AgentRequest.from_json({"output_schema": SCHEMA})
    with pytest.raises(ValueError):
        AgentRequest.from_json({"task": "do something"})


def test_request_mode_defaults_to_chat():
    assert make_request().mode == "chat"
    assert make_request(mode="rag_validation").mode == "rag_validation"


# --------------------------------------------------------- validation modes
def make_validation_request(mode, schema, fallback, context):
    return AgentRequest(
        goal="{}_validation".format(mode),
        task="Check the subject below.",
        context=context,
        output_schema=schema,
        fallback=fallback,
        mode="{}_validation".format(mode),
    )


def test_mcp_validation_mode_runs_through_the_same_loop():
    client = StubClient(['{"valid": "true", "notes": "matches the request.", "confidence": "high"}'])
    request = make_validation_request(
        "mcp", MCP_VALIDATION_SCHEMA,
        {"valid": "true", "notes": "unchecked", "confidence": "low"},
        {
            "tool_name": "check_review_quality",
            "arguments": {},
            "result": {"flagged": False, "reasons": ["no issues found"]},
        },
    )
    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["ok"] is True
    assert outcome["mode"] == "mcp_validation"
    assert outcome["result"]["valid"] == "true"
    assert outcome["result"]["notes"] == (
        "The registered MCP tool returned a structured result with no reported errors."
    )


def test_mcp_validation_rejects_a_tool_result_with_an_actual_error():
    client = StubClient([
        '{"valid": "true", "notes": "Everything is valid.", "confidence": "high"}'
    ])
    request = make_validation_request(
        "mcp",
        MCP_VALIDATION_SCHEMA,
        {},
        {
            "tool": "profile_check",
            "result": {
                "tool": "profile_check",
                "status": "invalid",
                "errors": ["joined_at must use ISO date format"],
            },
        },
    )

    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["fallback_used"] is False
    assert outcome["result"]["valid"] == "false"
    assert "joined_at must use ISO date format" in outcome["result"]["notes"]


def test_mcp_validation_replaces_a_contradictory_model_note():
    client = StubClient([
        '{"valid": "true", '
        '"notes": "Optional fields and errors might be missing.", '
        '"confidence": "high"}'
    ])
    request = make_validation_request(
        "mcp",
        MCP_VALIDATION_SCHEMA,
        {},
        {
            "tool": "profile_check",
            "result": {
                "tool": "profile_check",
                "status": "complete",
                "warnings": [],
                "errors": [],
            },
        },
    )

    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["result"] == {
        "valid": "true",
        "notes": (
            "The registered MCP tool returned a structured result with no reported errors."
        ),
        "confidence": "high",
    }


def test_rag_validation_mode_falls_back_when_the_model_is_unreachable():
    client = StubClient([OllamaError("connection refused")])
    request = make_validation_request(
        "rag", RAG_VALIDATION_SCHEMA,
        {
            "grounded": "false",
            "unsupported_claims": "Grounding could not be verified.",
            "confidence_ok": "false",
            "notes": "The answer was not verified.",
        },
        {"query": "Is the battery good?", "answer": "Reviewers like the battery life.", "sources": []},
    )
    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["fallback_used"] is True
    assert outcome["mode"] == "rag_validation"
    assert outcome["result"]["grounded"] == "false"


def test_rag_validation_supported_answer_has_consistent_fields():
    client = StubClient([
        '{"grounded": "false", "unsupported_claims": "none", '
        '"confidence_ok": "false"}'
    ])
    answer = "Returns are accepted within thirty days."
    request = make_validation_request(
        "rag",
        RAG_VALIDATION_SCHEMA,
        {},
        {
            "query": "When are returns accepted?",
            "answer": answer,
            "confidence": "medium",
            "sources": [{"snippet": answer, "section": "Returns"}],
        },
    )

    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["fallback_used"] is False
    assert outcome["result"] == {
        "grounded": "true",
        "unsupported_claims": "none",
        "confidence_ok": "true",
        "notes": "The answer is supported by the retrieved evidence.",
    }


def test_rag_validation_unsupported_answer_has_consistent_fields():
    client = StubClient([
        '{"grounded": "true", "unsupported_claims": "none", '
        '"confidence_ok": "true"}'
    ])
    request = make_validation_request(
        "rag",
        RAG_VALIDATION_SCHEMA,
        {},
        {
            "query": "Can I return this after sixty days?",
            "answer": "Returns are accepted after sixty days.",
            "confidence": "high",
            "sources": [{"snippet": "Returns are accepted within thirty days."}],
        },
    )

    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["fallback_used"] is False
    assert outcome["result"]["grounded"] == "false"
    assert outcome["result"]["confidence_ok"] == "false"
    assert outcome["result"]["unsupported_claims"] == (
        "The answer is not directly supported by the supplied source excerpts."
    )
    assert outcome["result"]["notes"] == (
        "The answer is not fully supported by the retrieved evidence. "
        "Unsupported claims: The answer is not directly supported by the supplied "
        "source excerpts."
    )


def test_rag_validation_adapts_when_structured_fields_disagree():
    client = StubClient([
        '{"grounded": "true", "unsupported_claims": "The delivery claim", '
        '"confidence_ok": "true"}',
        '{"grounded": "false", "unsupported_claims": "The delivery claim", '
        '"confidence_ok": "true"}',
    ])
    request = make_validation_request(
        "rag",
        RAG_VALIDATION_SCHEMA,
        {},
        {
            "query": "Is delivery free?",
            "answer": "Delivery is always free.",
            "sources": [{"snippet": "Delivery charges depend on the order."}],
        },
    )

    outcome = AgenticLoop(client=client, max_attempts=2).run(request)

    assert outcome["attempts"] == 2
    assert outcome["result"]["grounded"] == "false"
    assert "Adapt" in [step["step"] for step in outcome["trace"]]
    assert "must be 'none'" in client.prompts[1]
