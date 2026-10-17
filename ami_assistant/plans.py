"""The router's output: an intent, its grounding category, and the read-only tool calls to run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ami_assistant.players import PlayerRef


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Plan:
    intent: str
    grounding: str
    calls: list[ToolCall] = field(default_factory=list)
    players: list[PlayerRef] = field(default_factory=list)
    year_range: tuple[int, int] | None = None
    window: int | None = None
    stats: list[str] = field(default_factory=list)
    focus: str = ""
    position: str = ""
    page: str = ""
    action: str = ""
    clarification: str = ""
    notes: list[str] = field(default_factory=list)
    used_context: list[str] = field(default_factory=list)
    # Fantasy questions: the week asked about (if any) and the subject player's name as typed.
    week: int | None = None
    subject: str = ""

    @property
    def tool_names(self) -> list[str]:
        return [c.name for c in self.calls]
