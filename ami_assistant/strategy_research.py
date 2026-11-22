"""A2 research bridge: the selected Draft Strategy inside AMI's research answers.

* ``resolve_top_question``: "Compare my top two first basemen" → the players are resolved from the user's
  strategy (by the user's own ranking), then the existing stat tools answer the rewritten question.
* ``membership_line``: one line after a player research answer saying where those players sit in the
  selected strategy ("In your **Power** strategy: Aaron Judge #3 (pinned); Juan Soto isn't in it.").

Both go through AMI's read-only registry, so the Pro gate and the store's access check apply exactly as
for the A1 tools. Signed-out visitors, non-entitled users and users with no selected strategy get no
membership line and no storage read beyond the access check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ami_assistant.tools.strategy_research import POSITION_WORDS, position_code

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4}
_POSITION_ALTERNATION = "|".join(
    sorted({re.escape(w) for words in POSITION_WORDS.values() for w in words if len(w) > 2}, key=len, reverse=True)
)
# "my top two first basemen", "my top 3 outfielders", "my top catcher"
_TOP = re.compile(
    rf"\bmy\s+top\s+(?:(?P<n>[1-4]|one|two|three|four)\s+)?(?P<pos>{_POSITION_ALTERNATION}|1b|2b|3b|ss|of)\b",
    re.IGNORECASE,
)
# "... in my Power-Hitting strategy" / "from my speed strategy"
_IN_STRATEGY = re.compile(r"\s*\b(?:in|from)\s+my\s+(?P<name>[A-Za-z0-9][\w' &-]{0,40}?)\s+strateg(?:y|ies)\b",
                          re.IGNORECASE)
_PLURAL_HINT = re.compile(r"(?:men|ers|s)$", re.IGNORECASE)

MEMBERSHIP_INTENTS = frozenset({"compare", "trend", "valuation", "player_profile", "player_seasons"})


@dataclass
class TopResolution:
    question: str = ""            # rewritten question for the normal router ("" when not resolved)
    lead: str = ""                # sentence put before the answer
    answer: str = ""              # complete answer when the stat tools aren't needed (refusal, too few)
    tool_result: Any = None


def resolve_top_question(question: str, call_tool) -> TopResolution | None:
    """None when the question isn't about the strategy's top players at a position."""
    m = _TOP.search(question)
    if not m:
        return None
    n_raw = (m.group("n") or "").lower()
    pos_text = m.group("pos")
    count = _NUMBERS.get(n_raw) or (int(n_raw) if n_raw.isdigit() else (2 if _PLURAL_HINT.search(pos_text) else 1))
    code = position_code(pos_text)
    if not code:
        return None
    named = _IN_STRATEGY.search(question)
    name = named.group("name").strip() if named else ""
    res = call_tool("strategy_top_at_position", {"position": code, "count": count, "name": name})
    if not getattr(res, "ok", False):
        return TopResolution(answer=str(getattr(res, "message", "") or "I couldn't read your strategy."),
                             tool_result=res)
    data = res.data or {}
    players = [p["name"] for p in data.get("players") or []]
    strategy = data.get("strategy") or "your strategy"
    label = _position_label(code, len(players))
    if len(players) < count or (count >= 2 and len(players) < 2):
        have = ", ".join(players) if players else "none"
        gap = (f" {data['without_position']} of its players have no position recorded."
               if data.get("without_position") else "")
        return TopResolution(answer=(f"Your **{strategy}** strategy has {len(players)} "
                                     f"{_position_label(code, len(players))} ({have}), so I can't take the top "
                                     f"{count}.{gap}"), tool_result=res)
    ranks = ", ".join(f"{p['name']} (#{p['rank']}{', pinned' if p.get('pinned') else ''})"
                      for p in data["players"])
    lead = f"From your **{strategy}** strategy, your top {_count_word(count)}{label}: {ranks}."
    if data.get("unsaved_changes"):
        lead += " (Saved version; the editor has unsaved changes.)"
    if data.get("never_saved"):
        lead += " (This strategy isn't saved yet.)"
    joined = players[0] if len(players) == 1 else ", ".join(players[:-1]) + " and " + players[-1]
    rewritten = question[: m.start()] + joined + question[m.end():]
    if named:
        rewritten = _IN_STRATEGY.sub("", rewritten, count=1)
    if len(players) == 1 and not re.search(r"\b(?:compare|vs|versus|how|stats|trend|value)\b", rewritten, re.I):
        rewritten = f"Tell me about {joined}"
    return TopResolution(question=" ".join(rewritten.split()), lead=lead, tool_result=res)


def membership_line(result: Any) -> str:
    """One line for the answer, or "" (no strategy selected, not entitled, signed out, nothing to say)."""
    if not getattr(result, "ok", False):
        return ""
    data = result.data or {}
    strategy = data.get("strategy")
    rows = data.get("players") or []
    if not strategy or not rows:
        return ""
    bits = []
    for r in rows:
        if r.get("in_strategy"):
            extra = ", ".join(x for x in ("pinned" if r.get("pinned") else "", "your note saved" if r.get("has_note") else "") if x)
            bits.append(f"{r['name']} #{r['rank']}" + (f" ({extra})" if extra else ""))
        else:
            bits.append(f"{r['name']} isn't in it")
    tail = ""
    if data.get("unsaved_changes"):
        tail = " (saved version; the editor has unsaved changes)"
    elif data.get("never_saved"):
        tail = " (not saved yet)"
    return f"In your **{strategy}** strategy{tail}: " + "; ".join(bits) + "."


def membership_players(plan: Any) -> list[str]:
    if getattr(plan, "intent", "") not in MEMBERSHIP_INTENTS:
        return []
    return [p.name for p in getattr(plan, "players", []) or [] if getattr(p, "name", "")]


def _count_word(n: int) -> str:
    return "" if n == 1 else {2: "two ", 3: "three ", 4: "four "}.get(n, f"{n} ")


def _position_label(code: str, n: int) -> str:
    singular = {"C": "catcher", "1B": "first baseman", "2B": "second baseman", "3B": "third baseman",
                "SS": "shortstop", "OF": "outfielder", "DH": "designated hitter", "SP": "starting pitcher",
                "RP": "relief pitcher", "P": "pitcher"}[code]
    if n == 1:
        return singular
    return singular[:-3] + "men" if singular.endswith("man") else singular + "s"

