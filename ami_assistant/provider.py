"""Answer providers — the only place a model would ever be called.

Today the app has no model integration and no model credentials, so the default provider
is ``DeterministicProvider`` (the grounded template writer). A model provider would
implement the same ``AnswerProvider.compose`` and receive exactly ``build_model_payload``:
the question, the narrow page context, the read-only tool schemas and the tool results —
already scrubbed — plus rules that forbid adding facts. Nothing provider-specific lives in
the tools, router or analytics modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ami_assistant.compose import ComposedAnswer, Composer
from ami_assistant.safety import scrub

GROUNDING_RULES = (
    "Answer only from the tool results provided. Do not add statistics, reasons, rankings or facts that are "
    "not in them. If the results don't answer the question, say so. Never claim to have changed anything in "
    "the app — you are read-only. For current MLB news or live stats, say the app's data doesn't cover it. "
    "Use player names, not gendered pronouns."
)


@dataclass
class ComposeRequest:
    question: str
    plan: Any  # router.Plan
    results: dict[str, list[Any]]  # tool name → [ToolResult]
    context: dict[str, Any]
    tool_schemas: list[dict[str, Any]]


class AnswerProvider(Protocol):
    name: str

    def compose(self, request: ComposeRequest) -> ComposedAnswer: ...


class DeterministicProvider:
    """Grounded template answers; no network, no model."""

    name = "deterministic"

    def __init__(self, latest_season: int = 0, first_season: int = 0) -> None:
        self._composer = Composer(latest_season, first_season)

    def compose(self, request: ComposeRequest) -> ComposedAnswer:
        return self._composer.compose(request.plan, request.results, request.question)


def build_model_payload(request: ComposeRequest) -> dict[str, Any]:
    """What a model provider would be sent. Scrubbed; contains no session state beyond ``context``."""
    payload = {
        "system": GROUNDING_RULES,
        "question": request.question,
        "intent": getattr(request.plan, "intent", ""),
        "grounding": getattr(request.plan, "grounding", ""),
        "page_context": request.context,
        "tools": request.tool_schemas,
        "tool_results": [res.as_dict() for calls in request.results.values() for res in calls],
    }
    return scrub(json.loads(json.dumps(payload, default=str)))
