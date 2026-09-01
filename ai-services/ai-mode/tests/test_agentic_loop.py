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
from agent.validators import parse_json, validate  # noqa: E402


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
