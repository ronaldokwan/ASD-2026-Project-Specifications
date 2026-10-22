"""The team's shared Multi-Agent workflow: Planner -> Worker -> Reviewer -> Human Review.

Every student backend calls this service instead of running its own agents, so
the whole integrated application demonstrates one consistent multi-agent
workflow:

    frontend -> backend/API -> Multi-Agent Server -> Planner -> Worker -> Reviewer -> Human Review

Planner   turns the caller's goal into a short, grounded plan.
Worker    executes the plan against the caller's context, producing a draft result.
Reviewer  checks the draft against the plan and context, flags risks, and
          recommends approve / revise / reject - a recommendation only.
Human review always makes the final call (``POST /workflow/<id>/human-review``):
approve, correct, partially accept or reject the Worker's result.
"""

import time
from dataclasses import dataclass, field

from .ollama_client import OllamaClient, OllamaError
from .validators import parse_json, validate

SYSTEM_PROMPT = (
    "You are part of a multi-agent workflow inside a retail management application. "
    "You always reply with a single valid JSON object and nothing else. "
    "You never invent facts that contradict the context you are given."
)

PLAN_SCHEMA = {
    "steps": {"type": "list", "min_items": 2, "max_items": 5, "item_max_words": 20},
}

REVIEW_SCHEMA = {
    "verdict": {"type": "enum", "values": ["approve", "revise", "reject"]},
    "recommendation": {"type": "string", "min_words": 3, "max_words": 60},
    "risks": {
        "type": "list", "min_items": 0, "max_items": 5, "item_max_words": 20,
        "required": False,
    },
}

# What a human can decide once Planner -> Worker -> Reviewer has run.
HUMAN_DECISIONS = ("approve", "correct", "partial_accept", "reject")


@dataclass
class WorkflowRequest:
    """One unit of work submitted to the Multi-Agent Server by a student backend."""

    goal: str  # short id, e.g. "restock_plan"
    task: str  # natural-language instruction
    context: dict = field(default_factory=dict)  # grounding facts from the DB
    output_schema: dict = field(default_factory=dict)  # the Worker's deliverable
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


class MultiAgentWorkflow:
    def __init__(self, client=None):
        self.client = client or OllamaClient()

    # ------------------------------------------------------------- Planner
    def plan(self, request):
        """Break the task into a short, grounded plan for the Worker to follow."""
        try:
            raw = self.client.generate(
                self._plan_prompt(request), system=SYSTEM_PROMPT, json_mode=True
            )
            data = parse_json(raw)
            cleaned, violations = validate(data, PLAN_SCHEMA)
            if violations:
                raise ValueError("; ".join(violations))
            return {"agent": "planner", "ok": True, "steps": cleaned["steps"]}
        except (OllamaError, ValueError, TypeError) as exc:
            return {
                "agent": "planner",
                "ok": False,
                "steps": ["Address the task directly using the supplied context."],
                "error": str(exc),
            }

    def _plan_prompt(self, request):
        lines = ["TASK: " + request.task, "GOAL: " + request.goal, ""]
        if request.context:
            lines.append("CONTEXT (facts available to the workflow):")
            for key, value in request.context.items():
                lines.append("- {}: {}".format(key, value))
            lines.append("")
        lines.append(
            "Break this task into 2 to 5 short, concrete steps a worker agent should "
            "follow to complete it. Reply with ONE JSON object: "
            '{"steps": ["step one", "step two", ...]}. '
            "Do not include markdown, code fences or any extra keys."
        )
        return "\n".join(lines)

    # -------------------------------------------------------------- Worker
    def work(self, request, plan):
        """Execute the Planner's steps against the context, producing a draft result."""
        try:
            raw = self.client.generate(
                self._work_prompt(request, plan), system=SYSTEM_PROMPT, json_mode=True
            )
            data = parse_json(raw)
            cleaned, violations = validate(data, request.output_schema)
            if violations:
                raise ValueError("; ".join(violations))
            return {"agent": "worker", "ok": True, "result": cleaned}
        except (OllamaError, ValueError, TypeError) as exc:
            return {
                "agent": "worker",
                "ok": False,
                "result": dict(request.fallback),
                "error": str(exc),
            }

    def _work_prompt(self, request, plan):
        lines = ["TASK: " + request.task, "", "PLAN (follow every step):"]
        for i, step in enumerate(plan["steps"], 1):
            lines.append("{}. {}".format(i, step))
        lines.append("")
        if request.context:
            lines.append("CONTEXT:")
            for key, value in request.context.items():
                lines.append("- {}: {}".format(key, value))
            lines.append("")
        lines.append("Reply with ONE JSON object using exactly these keys:")
        for name, rules in request.output_schema.items():
            lines.append("- {}: {}".format(name, _describe(rules)))
        lines.append("")
        lines.append("Do not include markdown, code fences, comments or any extra keys.")
        return "\n".join(lines)

    # ------------------------------------------------------------ Reviewer
    def review(self, request, plan, work):
        """Check the Worker's draft against the plan and context; recommend, don't decide."""
        try:
            raw = self.client.generate(
                self._review_prompt(request, plan, work),
                system=SYSTEM_PROMPT,
                json_mode=True,
            )
            data = parse_json(raw)
            cleaned, violations = validate(data, REVIEW_SCHEMA)
            if violations:
                raise ValueError("; ".join(violations))
            cleaned.setdefault("risks", [])
            return {"agent": "reviewer", "ok": True, **cleaned}
        except (OllamaError, ValueError, TypeError) as exc:
            return {
                "agent": "reviewer",
                "ok": False,
                "verdict": "revise",
                "recommendation": (
                    "Automated review was unavailable; a human must review this manually."
                ),
                "risks": [str(exc)],
                "error": str(exc),
            }

    def _review_prompt(self, request, plan, work):
        lines = ["TASK: " + request.task, "", "PLAN the worker followed:"]
        for i, step in enumerate(plan["steps"], 1):
            lines.append("{}. {}".format(i, step))
        lines.append("")
        lines.append("WORKER OUTPUT to review: " + str(work["result"]))
        lines.append("")
        if request.context:
            lines.append("CONTEXT:")
            for key, value in request.context.items():
                lines.append("- {}: {}".format(key, value))
            lines.append("")
        lines.append(
            "Check whether the worker output actually followed the plan, is consistent "
            "with the context, and is safe to publish. Reply with ONE JSON object: "
            '{"verdict": "approve"|"revise"|"reject", "recommendation": "...", '
            '"risks": ["..."]}. risks must be an empty list when verdict is approve. '
            "Do not include markdown, code fences or any extra keys."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ run
    def run(self, request):
        """Run Planner -> Worker -> Reviewer and return one auditable record.

        Always comes back with status "pending_human_review": the Reviewer's
        verdict is a recommendation, never the final decision. A human makes
        the final call separately through POST /workflow/<id>/human-review.
        """
        started = time.time()
        plan = self.plan(request)
        work = self.work(request, plan)
        review = self.review(request, plan, work)

        trace = [
            {
                "step": "Planner",
                "ok": plan["ok"],
                "detail": "Produced {} step(s).".format(len(plan["steps"]))
                if plan["ok"]
                else "Planning failed ({}); used a deterministic single-step plan.".format(
                    plan.get("error")
                ),
            },
            {
                "step": "Worker",
                "ok": work["ok"],
                "detail": "Executed the plan against the supplied context."
                if work["ok"]
                else "Worker failed ({}); used the caller-supplied fallback.".format(
                    work.get("error")
                ),
            },
            {
                "step": "Reviewer",
                "ok": review["ok"],
                "detail": "Verdict: {}. {}".format(
                    review["verdict"], review["recommendation"]
                ),
            },
        ]

        return {
            "ok": True,
            "status": "pending_human_review",
            "goal": request.goal,
            "task": request.task,
            "context": request.context,
            "plan": plan,
            "worker": work,
            "review": review,
            "trace": trace,
            "model": self.client.model,
            "elapsed_ms": int((time.time() - started) * 1000),
        }


def _describe(rules):
    """Turn one output_schema entry into a short instruction for the model."""
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
