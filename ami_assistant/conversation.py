"""Follow-up memory: the subject of the last answer, so "what about the last three years?"
and "who had more power?" keep the same players without repeating them.

Kept in the user's own session only (``SESSION_KEY``); it is not in any persistence
allowlist, so it is never saved to the cloud workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, MutableMapping

SESSION_KEY = "_ami_assistant_conversation"
MAX_TURNS = 8


@dataclass
class Turn:
    question: str
    answer: str
    intent: str
    grounding: str
    tools: list[str] = field(default_factory=list)


@dataclass
class ConversationState:
    intent: str = ""
    player_ids: list[str] = field(default_factory=list)
    player_names: list[str] = field(default_factory=list)
    year_range: list[int] | None = None
    window: int | None = None
    stats: list[str] = field(default_factory=list)
    position: str = ""
    page: str = ""
    # Fantasy follow-ups: the roster player last discussed (as typed) and the week.
    subject_player: str = ""
    week: int | None = None
    turns: list[Turn] = field(default_factory=list)

    def remember(
        self,
        *,
        intent: str,
        player_ids: list[str] | None = None,
        player_names: list[str] | None = None,
        year_range: list[int] | None = None,
        window: int | None = None,
        stats: list[str] | None = None,
        position: str = "",
        page: str = "",
        subject_player: str = "",
        week: int | None = None,
    ) -> None:
        """Update the subject only with what this turn actually established."""
        self.intent = intent
        if player_ids:
            # New subject: its range is whatever this turn used (None = full careers).
            self.player_ids = list(player_ids)[:3]
            self.player_names = list(player_names or [])[:3]
            self.year_range = list(year_range) if year_range else None
        elif year_range:
            self.year_range = list(year_range)
        if window:
            self.window = int(window)
        if stats:
            self.stats = list(stats)
        if position:
            self.position = position
        if subject_player:
            self.subject_player = subject_player
        if week:
            self.week = int(week)
        self.page = page or self.page

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        del self.turns[:-MAX_TURNS]

    def has_subject(self) -> bool:
        return bool(self.player_ids or self.position or self.intent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "player_ids": list(self.player_ids),
            "player_names": list(self.player_names),
            "year_range": list(self.year_range) if self.year_range else None,
            "window": self.window,
            "stats": list(self.stats),
            "position": self.position,
            "page": self.page,
            "subject_player": self.subject_player,
            "week": self.week,
            "turns": [t.__dict__.copy() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "ConversationState":
        if not isinstance(raw, dict):
            return cls()
        state = cls(
            intent=str(raw.get("intent") or ""),
            player_ids=[str(x) for x in raw.get("player_ids") or []][:3],
            player_names=[str(x) for x in raw.get("player_names") or []][:3],
            year_range=list(raw["year_range"]) if raw.get("year_range") else None,
            window=raw.get("window"),
            stats=[str(x) for x in raw.get("stats") or []],
            position=str(raw.get("position") or ""),
            page=str(raw.get("page") or ""),
            subject_player=str(raw.get("subject_player") or ""),
            week=raw.get("week") if isinstance(raw.get("week"), int) else None,
        )
        for t in raw.get("turns") or []:
            if isinstance(t, dict):
                state.turns.append(
                    Turn(
                        question=str(t.get("question") or ""),
                        answer=str(t.get("answer") or ""),
                        intent=str(t.get("intent") or ""),
                        grounding=str(t.get("grounding") or ""),
                        tools=[str(x) for x in t.get("tools") or []],
                    )
                )
        return state


def load_conversation(session: MutableMapping[str, Any] | None) -> ConversationState:
    if session is None:
        return ConversationState()
    return ConversationState.from_dict(session.get(SESSION_KEY))


def save_conversation(session: MutableMapping[str, Any] | None, state: ConversationState) -> None:
    if session is not None:
        session[SESSION_KEY] = state.to_dict()


def clear_conversation(session: MutableMapping[str, Any] | None) -> None:
    if session is not None:
        session.pop(SESSION_KEY, None)
