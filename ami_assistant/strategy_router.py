"""A1: route questions about the user's OWN saved Draft Strategies to the ``my_strategy`` intent.

``draft_strategy`` stays the general drafting-advice intent ("Should I draft for need or best
available?"). ``my_strategy`` needs a personal cue:
* "my / saved / selected … strategy" or "strategies";
* "did I rank / save / note", "my notes";
* "Global Queue";
* "this strategy" when a strategy is selected;
* "this queue" and "my priorities" on the Draft Strategy page;
* a follow-up to a ``my_strategy`` answer.

Players are matched later against the strategy's own entries, never guessed, so this module only
extracts the text the user typed.
"""

from __future__ import annotations

import re
from typing import Any

from ami_assistant.capabilities import APP_DATA
from ami_assistant.plans import Plan, ToolCall

MY_STRATEGY = "my_strategy"
STRATEGY_PAGE = "Draft Strategy Assistant"

# focus values (what the user asked about)
F_LIST, F_CONTENTS, F_RANK, F_MEMBER, F_NOTE, F_RESEARCH = "list", "contents", "rank", "member", "note", "research"
F_POSITIONS, F_PRIORITIES, F_DIFF, F_SUMMARY = "positions", "priorities", "diff", "summary"

_GENERIC_NAME = {"", "draft", "saved", "current", "selected", "open", "pro", "own", "personal", "new", "this", "that",
                 "draft strategy", "saved draft", "current draft", "pro draft"}
_MY_STRAT = re.compile(r"\b(?:my|saved|selected)\b(?:\s+[\w'’\-]+){0,4}?\s+strateg(?:y|ies)\b")
_THIS_STRAT = re.compile(r"\b(?:this|current|open|that)\s+(?:draft\s+)?strateg(?:y|ies)\b")
_SAVED_STRATS = re.compile(r"\bstrategies (?:do i|have i|i have|i've|did i)\b|\b(?:list|show) (?:all )?(?:of )?my strategies\b")
_GLOBAL = re.compile(r"\bglobal queue\b")
_DID_I = re.compile(r"\b(?:did i|have i|i've|i have|i)\s+(?:rank|ranked|save|saved|note|noted|write|wrote|written|pin|pinned)\b")
_MY_NOTES = re.compile(r"\bmy (?:research )?notes?\b|\bmy (?:research|findings)\b|\bnotes? (?:i|did i|have i)\b")
_THIS_QUEUE = re.compile(r"\b(?:this|the) (?:queue|list)\b")
_MY_QUEUE = re.compile(r"\bmy queue\b")
_PRIORITIES = re.compile(r"\bpriorit\w*|\bpreferences?\b|\bwhat (?:do|does) (?:i|it|this strategy) (?:value|prefer)\b")
_POSITIONAL = re.compile(r"\bpositional\b|\bpositions?\b")
_NOT_STRATEGY = re.compile(r"\b(?:lineup|roster|waivers?|trade|trades|league|standings|my team|bench|week)\b")
_FOLLOW = re.compile(r"^(?:what about|how about|and|also|ok(?:ay)?|now|where(?:'s| is)|is|what did i)\b")

_LIST = re.compile(r"\b(?:which|what|list|show|how many)\b.*\bstrategies\b|\bstrategies (?:do i|have i|i have|i've)\b")
_DIFF = re.compile(r"\b(?:differ\w*|difference\w*|compare\w*|comparison|versus|vs\.?|different|overlap\w*|in common)\b")
_RESEARCH = re.compile(r"\bresearch\b|\bfindings?\b")
_NOTE = re.compile(r"\bnotes?\b|\bnoted\b|\bwrote\b|\bwritten\b")
_RANK = re.compile(r"\brank(?:ed|ing)?\b|\bwhere (?:is|did|do|does|was)\b|\bwhere's\b|\bwhat (?:number|spot|slot)\b")
_MEMBER = re.compile(r"^(?:is|are|do i have|did i (?:add|include|put))\b|\b(?:is|are) [\w .'’\-]+ (?:in|on) (?:my|this|the)\b")
_HOW_MANY = re.compile(r"\bhow many\b|\bcount\b|\bnumber of\b")
_CONTENTS = re.compile(r"\bwho(?:'s| is| are)? in\b|\bwhat(?:'s| is| players| players are)? in\b|\bwhat players\b"
                       r"|\b(?:show|list)\b|\bwho do i have\b|\btop \d+\b|\bwhat does (?:it|my|this)\b.*\bhave\b")

# The player as typed (matched later against the strategy's own entries).
_SUBJECT = (
    re.compile(r"\brank(?:ed)?\s+(?P<p>.+?)(?:\s+(?:in|on|at|for)\b|[?.!]|$)", re.I),
    re.compile(r"\bwhere(?:'s| is| was| did i (?:rank|put))\s+(?P<p>.+?)(?:\s+(?:ranked|rank|in|on)\b|[?.!]|$)", re.I),
    re.compile(r"^(?:is|are)\s+(?P<p>.+?)\s+(?:in|on)\s+(?:my|this|the)\b", re.I),
    re.compile(r"\b(?:do i have|did i (?:add|include|put|pin))\s+(?P<p>.+?)(?:\s+(?:in|on)\b|[?.!]|$)", re.I),
    re.compile(r"\b(?:about|on|for)\s+(?P<p>(?!my\b|this\b|the\b)[A-Za-z][\w .'’\-]+?)(?:\s+(?:in|on)\s+(?:my|this|the)\b|[?.!]|$)", re.I),
    re.compile(r"^(?:what about|how about|and)\s+(?P<p>.+?)[?.!]?$", re.I),
)
_STRAT_NAME = (
    re.compile(r"\bmy\s+(?P<n>[\w'’\- ]+?)\s+strategy\b"),
    re.compile(r"\b(?:strategy|plan) (?:called|named)\s+[\"“']?(?P<n>[\w'’\- ]+?)[\"”']?(?:[?.!,]|$)"),
    re.compile(r"\bin\s+(?P<n>[\w'’\- ]+?)\s+strategy\b"),
)


def _low(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("’", "'")).strip()


def strategy_name_hint(question: str) -> str:
    low = _low(question)
    for pat in _STRAT_NAME:
        m = pat.search(low)
        if not m:
            continue
        name = re.sub(r"^(?:the|my|saved|selected|current|draft|pro)\s+", "", m.group("n").strip())
        name = re.sub(r"\s+(?:draft|pro)$", "", name).strip()
        if name not in _GENERIC_NAME and not re.fullmatch(r"(?:saved|selected|current|draft|pro|\s)+", name):
            return name
    return ""


def original_case(question: str, fragment: str) -> str:
    """``fragment`` (found in the lower-cased question) as the user typed it."""
    if not fragment:
        return ""
    m = re.search(re.escape(fragment).replace("\\ ", r"\s+"), str(question or ""), re.I)
    return m.group(0) if m else fragment


def subject_text(question: str) -> str:
    raw = str(question or "").strip()
    for pat in _SUBJECT:
        m = pat.search(raw)
        if m:
            text = m.group("p").strip(" ?.!,'\"“”")
            text = re.sub(r"^(?:my|this|the)\s+", "", text, flags=re.I)
            if text and not re.fullmatch(r"(?i)(?:it|them|him|her|that|this|there|my strategy|this strategy|my queue)", text):
                return text[:60]
    return ""


def focus_of(low: str, position: str) -> str:
    if _LIST.search(low) and not _GLOBAL.search(low):
        return F_LIST
    if _GLOBAL.search(low) and _DIFF.search(low):
        return F_DIFF
    if _RESEARCH.search(low):
        return F_RESEARCH
    if _NOTE.search(low):
        return F_NOTE
    if _PRIORITIES.search(low) or (_POSITIONAL.search(low) and not position and not _HOW_MANY.search(low)):
        return F_PRIORITIES
    if position and (_HOW_MANY.search(low) or re.search(r"\b(?:which|what|who)\b", low)):
        return F_POSITIONS
    if _RANK.search(low):
        return F_RANK
    if _MEMBER.search(low):
        return F_MEMBER
    if _CONTENTS.search(low):
        return F_CONTENTS
    return F_SUMMARY


def is_my_strategy_question(low: str, ctx: Any, conv: Any) -> bool:
    selected = bool((getattr(ctx, "strategy", None) or {}).get("selected"))
    on_page = getattr(ctx, "page", "") == STRATEGY_PAGE
    last = getattr(conv, "intent", "") if conv is not None else ""
    if _MY_STRAT.search(low) or _SAVED_STRATS.search(low) or _GLOBAL.search(low):
        return True
    if _NOT_STRATEGY.search(low):
        return False
    if _THIS_STRAT.search(low) and (selected or on_page):
        return True
    if _DID_I.search(low) or _MY_NOTES.search(low):
        return True
    if on_page and (_THIS_QUEUE.search(low) or _MY_QUEUE.search(low) or
                    (_PRIORITIES.search(low) and re.search(r"\bmy\b", low))):
        return True
    if last == MY_STRATEGY and _FOLLOW.search(low) and len(low) <= 80:
        return True
    return False


_HOWTO = re.compile(r"^(?:how (?:do|can|would|should|could) (?:i|we|you)|how to|show me how|steps to|walk me through"
                    r"|is there a way to|where (?:do|can|would|should) i)\b")


def strategy_plan(question: str, ctx: Any, conv: Any, position: str = "") -> Plan | None:
    low = _low(question)
    if _HOWTO.search(low) or not is_my_strategy_question(low, ctx, conv):
        return None
    focus = focus_of(low, position)
    hint = strategy_name_hint(question)
    followup = not hint and getattr(conv, "intent", "") == MY_STRATEGY and not (
        _MY_STRAT.search(low) or _THIS_STRAT.search(low) or _GLOBAL.search(low))
    subject = subject_text(question)
    if followup:
        hint = str(getattr(conv, "strategy", "") or "")
        if focus == F_SUMMARY:
            last = str(getattr(conv, "strategy_focus", "") or "")
            if subject:  # "What about Pete Alonso?": the same question about another player
                focus = last if last in (F_RANK, F_MEMBER, F_NOTE) else F_RANK
            else:
                focus = last or F_SUMMARY
    used = [] if hint else ["selected_strategy"]
    if focus == F_LIST:
        calls = [ToolCall("list_my_strategies", {})]
    elif focus == F_DIFF:
        calls = [ToolCall("compare_strategy_to_global", {"name": hint})]
    elif _GLOBAL.search(low) or (_MY_QUEUE.search(low) and not _MY_STRAT.search(low)) or (
            _THIS_QUEUE.search(low) and not (getattr(ctx, "strategy", None) or {}).get("selected")):
        calls, used = [ToolCall("get_global_list", {})], ["global_queue"]
    else:
        args = {"name": hint}
        if subject and focus in (F_RANK, F_MEMBER, F_NOTE):
            args["player"] = subject
        calls = [ToolCall("get_my_strategy", args)]
    return Plan(MY_STRATEGY, APP_DATA, calls, focus=focus, position=position, subject=subject, used_context=used)


_STRATEGY_TARGET = re.compile(r"\bstrateg(?:y|ies)\b|\bglobal queue\b|\bmy queue\b")
_ADD_TO = re.compile(r"^(?:ami[,:]?\s+)?(?:please\s+|can you\s+|could you\s+)*(?:add|put|queue|insert)\s+(?P<p>.+?)"
                     r"\s+(?:to|into|in|on)\s+", re.I)


def strategy_action_plan(question: str, action: str) -> Plan | None:
    """A change request aimed at a strategy or the Global Queue ("Add Judge to my Speed strategy").
    A1 is read-only: say so plainly and point to the control that does it (no waiver/roster wording)."""
    low = _low(question)
    if not action or not _STRATEGY_TARGET.search(low):
        return None
    m = _ADD_TO.search(str(question or "").strip())
    who = f"**{m.group('p').strip()}**" if m else "players"
    if _GLOBAL.search(low) or (_MY_QUEUE.search(low) and not re.search(r"\bstrateg", low)):
        text = (f"I can't change your Global Queue; AMI only reads it for now. To add {who}, use **⭐ Add to Queue** "
                "on Draft Strategy · PRO's recommendations or on a research page. Nothing was changed.")
    else:
        name = original_case(question, strategy_name_hint(question))
        target = f"**{name}**" if name else "the strategy"
        text = (f"I can't change your strategies; AMI only reads them for now. To add {who} to {target}, open "
                f"**Draft Strategy · PRO**, choose {target}, use **Add to this strategy** on its Queue tab, then "
                "**Save strategy**. Other strategies and your Global Queue aren't affected. Nothing was changed.")
    from ami_assistant.capabilities import PRODUCT_HELP

    return Plan(MY_STRATEGY, PRODUCT_HELP, [], focus="action", clarification=text)
