"""The team's shared Agentic AI workflow: Plan -> Act -> Observe -> Adapt.

Every student backend calls this loop through the AI-Mode service instead of
calling Ollama directly, so the whole integrated application demonstrates one
consistent agentic workflow.

    Plan    build a grounded prompt from the caller's task plus context facts
            retrieved from that student's database microservice
    Act     call the approved open-source LLM through the Ollama runtime
    Observe parse the answer and validate it against the caller's schema
    Adapt   re-prompt with the exact violations, or fall back deterministically
"""

import os
import time
from dataclasses import dataclass, field

from .ollama_client import OllamaClient, OllamaError
from .validators import parse_json, validate

SYSTEM_PROMPT = (
    "You are the AI assistant inside a retail management application. "
    "You always reply with a single valid JSON object and nothing else. "
    "You never invent facts that contradict the context you are given."
)


@dataclass
class AgentRequest:
    """One unit of work submitted to the agentic loop by a student backend."""

    goal: str  # short id, e.g. "product_copy"
    task: str  # natural-language instruction
    context: dict = field(default_factory=dict)  # grounding facts from the DB
    output_schema: dict = field(default_factory=dict)
    fallback: dict = field(default_factory=dict)  # deterministic safety net

    @classmethod
    def from_json(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        if not payload.get("task"):
            raise ValueError("'task' is required")
        if (
            not isinstance(payload.get("output_schema"), dict)
            or not payload["output_schema"]
        ):
            raise ValueError(
                "'output_schema' is required and must be a non-empty object"
            )
        return cls(
            goal=payload.get("goal", "unspecified"),
            task=payload["task"],
            context=payload.get("context") or {},
            output_schema=payload["output_schema"],
            fallback=payload.get("fallback") or {},
        )


class AgenticLoop:
    def __init__(self, client=None, max_attempts=None):
        self.client = client or OllamaClient()
        self.max_attempts = int(
            max_attempts or os.getenv("AI_MODE_MAX_ADAPT_ATTEMPTS", "2")
        )

    # ------------------------------------------------------------------ PLAN
    def plan(self, request, violations=None):
        """Build the prompt. On an Adapt pass, violations are folded back in."""
        lines = ["TASK: " + request.task, ""]

        if request.context:
            lines.append("CONTEXT (facts retrieved from the application database):")
            for key, value in request.context.items():
                lines.append("- {}: {}".format(key, value))
            lines.append("")

        lines.append("Reply with ONE JSON object using exactly these keys:")
        for name, rules in request.output_schema.items():
            lines.append("- {}: {}".format(name, _describe(rules)))
        lines.append("")

        if violations:
            lines.append(
                "Your previous answer was rejected for these reasons. Fix all of them:"
            )
            lines.extend("- " + v for v in violations)
            lines.append("")

        lines.append(
            "Do not include markdown, code fences, comments or any extra keys."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------- ACT
    def act(self, prompt):
        return self.client.generate(prompt, system=SYSTEM_PROMPT, json_mode=True)

    # --------------------------------------------------------------- OBSERVE
    def observe(self, raw, request):
        """Parse and validate one model answer; returns (result, violations)."""
        try:
            data = parse_json(raw)
        except (ValueError, TypeError) as exc:
            return {}, ["output was not valid JSON ({})".format(exc)]
        return validate(data, request.output_schema)

    # ------------------------------------------------------------------- RUN
    def run(self, request):
        """Execute the full loop and return a result plus an auditable trace."""
        trace = []
        violations = []
        started = time.time()

        for attempt in range(1, self.max_attempts + 1):
            step = "Plan" if attempt == 1 else "Adapt"
            prompt = self.plan(request, violations)
            if attempt == 1:
                detail = "Built a grounded prompt for goal '{}' with {} context fact(s).".format(
                    request.goal, len(request.context)
                )
            else:
                detail = (
                    "Re-planned the prompt with the previous violations: "
                    + "; ".join(violations)
                )
            trace.append({"step": step, "attempt": attempt, "detail": detail})

            try:
                raw = self.act(prompt)
            except OllamaError as exc:
                trace.append(
                    {
                        "step": "Act",
                        "attempt": attempt,
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                return self._fallback(request, trace, str(exc), started)

            trace.append(
                {
                    "step": "Act",
                    "attempt": attempt,
                    "detail": "Called {} through the Ollama runtime.".format(
                        self.client.model
                    ),
                    "raw_preview": raw[:280],
                }
            )

            result, violations = self.observe(raw, request)
            if not violations:
                trace.append(
                    {
                        "step": "Observe",
                        "attempt": attempt,
                        "status": "passed",
                        "detail": "Output parsed and satisfied every guardrail.",
                    }
                )
                return {
                    "ok": True,
                    "result": result,
                    "attempts": attempt,
                    "fallback_used": False,
                    "model": self.client.model,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "trace": trace,
                }

            trace.append(
                {
                    "step": "Observe",
                    "attempt": attempt,
                    "status": "failed",
                    "detail": "Guardrails rejected the output: "
                    + "; ".join(violations),
                }
            )

        return self._fallback(request, trace, "; ".join(violations), started)

    # -------------------------------------------------------------- FALLBACK
    def _fallback(self, request, trace, reason, started):
        """Adapt of last resort: never leave the calling UI without an answer."""
        trace.append(
            {
                "step": "Adapt",
                "status": "fallback",
                "detail": (
                    "Exhausted the retry budget, so the deterministic fallback supplied by "
                    "the calling microservice was used instead. Reason: " + str(reason)
                ),
            }
        )
        return {
            "ok": bool(request.fallback),
            "result": request.fallback,
            "attempts": self.max_attempts,
            "fallback_used": True,
            "error": reason,
            "model": self.client.model,
            "elapsed_ms": int((time.time() - started) * 1000),
            "trace": trace,
        }


def _describe(rules):
    """Turn one schema entry into a short instruction for the model."""
    kind = rules.get("type", "string")
    parts = [kind]
    if kind in ("number", "integer"):
        if "min" in rules and "max" in rules:
            parts.append("between {} and {}".format(rules["min"], rules["max"]))
        parts.append("plain number, no currency symbol")
    elif kind == "enum":
        parts.append("one of " + ", ".join(str(v) for v in rules.get("values", [])))
    else:
        if "min_words" in rules or "max_words" in rules:
            parts.append(
                "{}-{} words".format(
                    rules.get("min_words", 1), rules.get("max_words", 80)
                )
            )
    if rules.get("hint"):
        parts.append(rules["hint"])
    return ", ".join(parts)
