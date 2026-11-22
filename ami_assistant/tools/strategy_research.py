"""A2: AMI's research bridge to the user's selected Draft Strategy (read-only).

Two tools the research answers use, built on the A1 helpers and rules:

* ``strategy_membership``: where the players an answer is about sit in the selected strategy
  ("Aaron Judge is #3 in Power, pinned"). Used after a research answer is composed.
* ``strategy_top_at_position``: the strategy's top players at a position ("my top two first basemen"),
  so the existing stat tools can compare them.

Same safety as A1: the store's own access check (signed in + the page's Pro entitlement) runs before any
read, the registry gate uses ``plan_capability="draft_strategy_library"``, session values are only read
with ``.get``, deleted strategies are never opened, and only the user's own records are quoted.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ami_assistant.safety import clean_text
from ami_assistant.tools.registry import ToolResult, fail, tool
from ami_assistant.tools.strategy import (
    CAPABILITY,
    NAME_LIMIT,
    PLAN_CAPABILITY,
    _live,
    _open_id,
    _pick,
    _view,
    _work_records,
    player_key,
)

MEMBERSHIP_PLAYER_LIMIT = 6
TOP_LIMIT = 4
NOT_ENOUGH = "not_enough_at_position"

# Positions as the user says them → the codes stored on strategy entries.
POSITION_WORDS: dict[str, tuple[str, ...]] = {
    "C": ("catcher", "catchers", "c"),
    "1B": ("first baseman", "first basemen", "first base", "1b"),
    "2B": ("second baseman", "second basemen", "second base", "2b"),
    "3B": ("third baseman", "third basemen", "third base", "3b"),
    "SS": ("shortstop", "shortstops", "ss"),
    "OF": ("outfielder", "outfielders", "outfield", "of"),
    "DH": ("designated hitter", "designated hitters", "dh"),
    "SP": ("starting pitcher", "starting pitchers", "starter", "starters", "sp"),
    "RP": ("relief pitcher", "relief pitchers", "reliever", "relievers", "closer", "closers", "rp"),
    "P": ("pitcher", "pitchers", "p"),
}
# An entry stored with any of these codes counts for the position asked about.
POSITION_MATCHES: dict[str, frozenset[str]] = {
    "OF": frozenset({"OF", "LF", "CF", "RF"}),
    "P": frozenset({"P", "SP", "RP"}),
}


def position_code(text: str) -> str:
    """'first basemen' → '1B'; '' when the text names no position."""
    low = " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).split())
    for code, words in POSITION_WORDS.items():
        if low in words:
            return code
    return ""


def _entry_codes(entry: Mapping[str, Any]) -> set[str]:
    return {t for t in re.split(r"[^A-Z0-9]+", str(entry.get("position") or "").upper()) if t}


def _plays(entry: Mapping[str, Any], code: str) -> bool:
    return bool(_entry_codes(entry) & POSITION_MATCHES.get(code, frozenset({code})))


def _selected_view(session: Mapping[str, Any], strategies: list[dict[str, Any]]
                   ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The selected strategy's saved view (the editor's open one, or the only one), without asking.

    Returns (view or None, info). A research answer never asks "which strategy?": with several saved
    strategies and none selected, there is simply nothing to add.
    """
    recs = _work_records(session)
    open_id = _open_id(session)
    open_rec = recs.get(open_id) if isinstance(recs.get(open_id), dict) else None
    live = {str(s["id"]): s for s in strategies}
    if open_id in live:
        chosen, how = live[open_id], "selected"
    elif open_rec and open_rec.get("new") and isinstance(open_rec.get("strategy"), dict):
        return _view(open_rec["strategy"]), {"chosen_by": "selected", "never_saved": True}
    elif len(strategies) == 1:
        chosen, how = strategies[0], "only_one"
    else:
        return None, {"chosen_by": "", "strategies": len(strategies)}
    rec = recs.get(str(chosen["id"])) if isinstance(recs.get(str(chosen["id"])), dict) else None
    return _view(chosen), {"chosen_by": how, "unsaved_changes": bool(rec and rec.get("dirty"))}


@tool(
    "strategy_membership", capability=CAPABILITY, needs_session=True, plan_capability=PLAN_CAPABILITY,
    description=("Where the given players sit in the user's selected Draft Strategy: rank, pinned, whether "
                 "the user saved a note. Read-only; nothing when no strategy is selected."),
    parameters={"properties": {"players": {"type": "array", "items": {"type": "string"},
                                           "description": "Player names from the answer."}},
                "required": ["players"]},
    reuses=("draft_strategy_v2.list_strategies_v2",),
)
def strategy_membership(*, session: Mapping[str, Any], players: list[str] | None = None) -> ToolResult:
    names = [clean_text(p, NAME_LIMIT) for p in (players or [])][:MEMBERSHIP_PLAYER_LIMIT]
    names = [n for n in names if n]
    strategies, failure = _live(session, "strategy_membership")
    if failure is not None:
        return failure
    view, info = _selected_view(session, strategies)
    if view is None or not names:
        return ToolResult("strategy_membership", True, {"strategy": None, "players": [], **info})
    # Exact full names only: the answer's players are resolved names, so a shared last name
    # ("Geovany Soto" vs "Juan Soto") must never count as membership.
    by_key = {player_key(e["name"]): e for e in view["entries"]}
    rows = []
    for name in names:
        hit = by_key.get(player_key(name))
        rows.append({"name": name, "in_strategy": hit is not None,
                     "rank": hit["rank"] if hit else None, "pinned": bool(hit and hit["pinned"]),
                     "has_note": bool(hit and hit["note"])})
    return ToolResult("strategy_membership", True, {
        "strategy": view["name"], "size": len(view["entries"]), "players": rows, **info})


@tool(
    "strategy_top_at_position", capability=CAPABILITY, needs_session=True, plan_capability=PLAN_CAPABILITY,
    description=("The top players at one position in the user's Draft Strategy (the selected one unless a "
                 "name is given), by the user's own ranking. Read-only."),
    parameters={"properties": {"position": {"type": "string"}, "count": {"type": "integer"},
                               "name": {"type": "string", "description": "A strategy name as the user typed it."}},
                "required": ["position"]},
    reuses=("draft_strategy_v2.list_strategies_v2",),
)
def strategy_top_at_position(*, session: Mapping[str, Any], position: str = "", count: int = 2,
                             name: str = "") -> ToolResult:
    code = position_code(position) or str(position or "").upper().strip()
    if code not in POSITION_WORDS:
        return fail("strategy_top_at_position", "unknown_position", "I didn't recognise that position.")
    want = max(1, min(int(count or 2), TOP_LIMIT))
    strategies, failure = _live(session, "strategy_top_at_position")
    if failure is not None:
        return failure
    chosen, unsaved, how, failure = _pick(session, strategies, str(name or "").strip(), "strategy_top_at_position")
    if failure is not None:
        return failure
    view = _view(chosen) if chosen is not None else unsaved
    if not isinstance(view, dict):
        return fail("strategy_top_at_position", "no_strategies", "I couldn't read that strategy.")
    at_pos = [e for e in view["entries"] if _plays(e, code)]
    no_position = sum(1 for e in view["entries"] if not _entry_codes(e))
    data = {"strategy": view["name"], "position": code, "requested": want,
            "players": [{"name": e["name"], "rank": e["rank"], "pinned": e["pinned"]} for e in at_pos[:want]],
            "at_position": len(at_pos), "without_position": no_position,
            "never_saved": bool(how.get("never_saved")),
            "unsaved_changes": unsaved is not None and chosen is not None}
    return ToolResult("strategy_top_at_position", True, data)
