"""Fantasy league questions → read-only fantasy tools (Phase D interfaces).

Kept apart from ``router`` because the vocabulary is different (league standings, weeks, lineup
slots, trades) and the subjects are league rosters, not the historical player database.

Rules that matter:

* "standings" means **official** standings (sum of finalized weeks). Only an explicit "current
  roster(s)" / "would rank" question gets the current-roster what-if, and it keeps its label;
* asking about the difference between the two is product help;
* how-to questions with a known how-to ("How do I check the standings?") stay product help;
* nothing here can produce a write: lineup, waiver and trade requests phrased as instructions
  were already refused by ``router.detect_action``.
"""

from __future__ import annotations

import re
from typing import Any

from ami_assistant.capabilities import APP_DATA, PRODUCT_HELP
from ami_assistant.context import AmiPageContext
from ami_assistant.conversation import ConversationState
from ami_assistant.glossary import match_term
from ami_assistant.page_help import find_howto
from ami_assistant.plans import Plan, ToolCall

F_LEAGUE = "fantasy_league"
F_STANDINGS = "fantasy_standings"
F_SNAPSHOT = "fantasy_roster_snapshot"
F_GAINS = "fantasy_gains"
F_STRENGTHS = "fantasy_strengths"
F_WEEK = "fantasy_week"
F_WEEK_LINEUP = "fantasy_week_lineup"
F_PLAYER_WEEK = "fantasy_player_week"
F_LINEUP = "fantasy_lineup"
F_EMPTY = "fantasy_empty_slots"
F_ELIGIBLE = "fantasy_slot_eligibility"
F_FIND_ELIGIBLE = "fantasy_find_eligible"
F_TRADE = "fantasy_trade"
F_WAIVER = "fantasy_waiver"
FANTASY_INTENTS = frozenset({F_LEAGUE, F_STANDINGS, F_SNAPSHOT, F_GAINS, F_STRENGTHS, F_WEEK, F_WEEK_LINEUP,
                             F_PLAYER_WEEK, F_LINEUP, F_EMPTY, F_ELIGIBLE, F_FIND_ELIGIBLE, F_TRADE, F_WAIVER})
# Help terms that "what is / what does … mean" questions should explain rather than look up.
FANTASY_HELP_TERMS = frozenset({"official_standings", "current_roster_snapshot", "use_suggested_lineup",
                                "consider_add", "eligibility", "explore_more", "lineup_status", "trade_verdict",
                                "commissioner_tools"})

_POS = (r"(?:shortstop|ss|catcher|c|first base(?:man)?|1b|second base(?:man)?|2b|third base(?:man)?|3b|"
        r"outfield(?:er)?|of|util(?:ity)?|dh|designated hitter)")
SLOT_WORDS: tuple[tuple[str, str], ...] = (
    ("shortstop", "SS"), ("catcher", "C"), ("first baseman", "1B"), ("first base", "1B"),
    ("second baseman", "2B"), ("second base", "2B"), ("third baseman", "3B"), ("third base", "3B"),
    ("outfielder", "OF"), ("outfield", "OF"), ("utility", "UTIL"), ("util", "UTIL"), ("designated hitter", "DH"),
    ("ss", "SS"), ("1b", "1B"), ("2b", "2B"), ("3b", "3B"), ("of", "OF"), ("dh", "DH"), ("c", "C"),
)
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "eleven": 11, "twelve": 12}

_HOWTO = re.compile(r"^(?:how (?:do|can|would|should|could) (?:i|we|you)|how to|where (?:do|can|would|should) i (?:go|find|see|open|check|make|set|use)|show me how|steps to|walk me through)\b")
_DEFINITION = re.compile(r"^(?:what(?:'s| is| are| does| do)|whats|define|explain|meaning of)\b")
_TRADE = re.compile(r"\btrad(?:e|es|ing)\b")
_TRADE_EVAL = re.compile(r"\b(?:would|what if|what does|what would|how does|how would|evaluate|leave me|help me|if i|should i|is this|this trade|do to)\b")
_TRADE_SIDES = (
    re.compile(r"\btrad(?:e|ing)\s+(?P<give>.+?)\s+for\s+(?P<recv>.+?)(?=$|\?|,|\s+(?:leave|would|help|do|does|to|and get|improve|hurt|make)\b)", re.I),
    re.compile(r"\bgive\s+(?:up\s+)?(?P<give>.+?)\s+(?:and get|for|to get)\s+(?P<recv>.+?)(?=$|\?|,|\s+(?:would|leave|help|do|does)\b)", re.I),
)
_PLAYER_WEEK = re.compile(r"\b(?:didn'?t|did not|doesn'?t|does not|wasn'?t|was not)\b.*\bcount|\bwhy\b.*\bnot count")
_PLAYER_WEEK_NAME = re.compile(r"(?:didn'?t|did not|doesn'?t|does not|wasn'?t|was not)\s+(?P<p>.+?)\s+count|why\s+(?P<p2>.+?)\s+(?:didn'?t|did not|doesn'?t|wasn'?t)\s+count", re.I)
_WEEK_REF = re.compile(r"\b(?:last week|this week|week (?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve))\b")
_WEEK_LINEUP = re.compile(r"\blineup\b|\bwho (?:was|were) (?:in|starting|on)\b|\bstarters\b")
_WEEK_STATUS = re.compile(r"\bfinali[sz]ed?\b|\b(?:is|has) (?:this|last|the) week\b.*\b(?:final|over|done|scored)\b|\bbeen finali")
_WEEK_SUMMARY = re.compile(r"\bwhat happened\b|\bhow did (?:i|we|my team) do\b|\b(?:results?|recap|score[sd]?)\b|\blast week\b|\bweek \d+\b")
_DIFFERENCE = re.compile(r"\bdifference\b|\bvs\.?\b|\bversus\b|\bcompared? (?:to|with)\b")
_SNAPSHOT = re.compile(r"\bcurrent rosters?\b|\brosters? would rank\b|\bwould (?:my )?(?:current )?roster rank\b|\bhow would (?:my|our) (?:current )?(?:roster|team) rank\b|\broster snapshot\b")
_GAINS = re.compile(r"\bgain (?:a |any |more )?(?:roto )?points?\b|\b(?:pick up|get|earn|win) (?:a |more |some )?(?:roto )?points?\b|\bclosest gains?\b|\bmove up\b|\bcatch up\b")
_STRENGTHS = re.compile(r"\b(?:strongest|best|weakest|worst) categor|\bcategor\w* (?:am i|are we|is my team) (?:strongest|weakest|best|worst)|\bwhat am i (?:good|bad) at\b")
_STANDINGS = re.compile(r"\bstandings\b|\bwhat place\b|\bwhich place\b|\bwhere (?:am i|do i stand|do i rank|are we|does my team stand)\b|\bhow far\b.*\b(?:first|1st|lead|leader|top)\b|\bin first\b|\bmy (?:place|rank|ranking)\b|\bam i winning\b|\bwho(?:'s| is) (?:winning|leading|in first)\b")
_EMPTY = re.compile(r"\b(?:which|what) (?:positions?|slots?) (?:are|is) (?:empty|open|unfilled|missing)\b|\bempty (?:slots?|positions?)\b|\bopen (?:slots?|positions?)\b|\bunfill(?:ed|able)\b|\bcan'?t (?:i )?fill\b|\b(?:which|what) positions? needs? (?:the most )?help\b")
_ELIGIBLE = (
    re.compile(r"\bcan (?P<p>.+?) (?:play|start|go|fill|be (?:used|played|started))(?: at| in| as)?\b(?P<rest>.*)", re.I),
    re.compile(r"\bwhy (?:can'?t|cannot|can not|isn'?t|is not|won'?t) (?P<p>.+?) (?:play|start|go|be|fill|eligible)\b(?P<rest>.*)", re.I),
    re.compile(r"\bis (?P<p>.+?) eligible (?:at|for|to play)\b(?P<rest>.*)", re.I),
)
_FIND_ELIGIBLE = re.compile(rf"\bdo i have (?:an? |any )?(?:eligible )?{_POS}\b|\b(?:anyone|anybody|someone|somebody|who)\b.*\b(?:can|could) (?:help|play|fill|cover)\b|\bwho can play\b|\beligible {_POS}\b")
_LINEUP = re.compile(r"\bwho should i start\b|\bstart this week\b|\brecommended starters\b|\bmy (?:best )?lineup\b|\bstart or sit\b|\bstart/sit\b|\bmy (?:bench|starters)\b|\bwho(?:'s| is) (?:starting|on my bench)\b")
_WAIVER = re.compile(r"\bwaivers?\b|\bwaiver wire\b|\bfree agents?\b|\bpick ?up\b|\bwho should i (?:add|drop|pick up)\b|\bavailable players?\b|\bwaiver player\b|\bwho (?:can|could|should) i add\b")
_LEAGUE = re.compile(r"\b(?:which|what) league\b|\bmy league\b|\bwhat(?:'s| is) my team\b|\bwhich team is mine\b|\bam i (?:the )?commissioner\b|\bwho (?:is|are) (?:in )?my league\b")
_FOLLOWUP = re.compile(r"^(?:what about|how about|and\b|ok(?:ay)?\b|now\b)")
_THIS = re.compile(r"^(?:this player|that player|he|him|this slot|that slot|it)$")


def _low(text: str) -> str:
    return " " + re.sub(r"\s+", " ", str(text or "").lower().replace("’", "'")).strip() + " "


def parse_slot(text: str) -> str:
    low = _low(text)
    for word, code in SLOT_WORDS:
        if word in ("of", "c"):
            # "of" and "c" are ordinary words; only the capitalized abbreviations name a slot.
            if re.search(rf"(?<![A-Za-z0-9]){word.upper()}(?![A-Za-z0-9])", str(text or "")):
                return code
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", low):
            return code
    return ""


def parse_week(text: str) -> int | None:
    m = re.search(r"\bweek (\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", _low(text))
    if not m:
        return None
    return _NUM_WORDS.get(m.group(1)) or int(m.group(1))


def _clean_name(raw: str) -> str:
    name = re.sub(r"^(?:my |the |our |player )", "", str(raw or "").strip(" ?.!,'\""), flags=re.I)
    return re.sub(r"'s$", "", name).strip()


def _split_players(raw: str) -> list[str]:
    parts = re.split(r",\s*|\s+and\s+|\s*&\s*", str(raw or ""))
    return [p for p in (_clean_name(x) for x in parts) if p]


def _player_for(raw: str, conv: ConversationState, ctx: AmiPageContext) -> str:
    """The name the user typed, or the subject they referred to ("this player", "he")."""
    name = _clean_name(raw)
    if _THIS.match(name.lower()):
        if conv.subject_player:
            return conv.subject_player
        if conv.player_names:
            return conv.player_names[0]
        if ctx.players:
            return str(ctx.players[0]).split(" (")[0]
        return ""
    return name


def fantasy_plan(question: str, ctx: AmiPageContext, conv: ConversationState) -> Plan | None:
    """A plan for a fantasy league question, or None when it isn't one."""
    q = str(question or "").strip()
    low = _low(q)
    stripped = low.strip()
    orig = " " + re.sub(r"\s+", " ", q.replace("’", "'")).strip() + " "  # keeps names' case

    # Product help keeps priority: "How do I check the standings?", "What does Use Suggested Lineup do?"
    if _HOWTO.search(stripped) and find_howto(q) is not None:
        return None
    term, _ = match_term(q)
    if _DIFFERENCE.search(low) and ("standings" in low or "roster" in low) and ("official" in low or "current" in low):
        return Plan("help_metric", PRODUCT_HELP, [ToolCall("explain_metric", {"term": "official_standings"})])
    if _DEFINITION.search(stripped) and term is not None and term.key in FANTASY_HELP_TERMS:
        return None

    week = parse_week(q)
    slot = parse_slot(q)
    followup = bool(_FOLLOWUP.search(stripped)) and conv.intent in FANTASY_INTENTS

    if _TRADE.search(low) and (_TRADE_EVAL.search(low) or "?" in q):
        for pattern in _TRADE_SIDES:
            m = pattern.search(orig)
            if m:
                give, recv = _split_players(m.group("give")), _split_players(m.group("recv"))
                if give and recv:
                    args: dict[str, Any] = {"give": give, "receive": recv}
                    if slot:
                        args["slot"] = slot
                    return Plan(F_TRADE, APP_DATA, [ToolCall("evaluate_trade", args)], position=slot)
        if re.search(r"\b(?:this|the|that) trade\b", low):
            return Plan(F_TRADE, APP_DATA, position=slot, clarification=(
                "AMI can't read the trade you're building in Trade Center yet. Name the players, e.g. "
                "“Would trading Aaron Judge for Kyle Tucker leave me without a catcher?”"))

    if _PLAYER_WEEK.search(low):
        m = _PLAYER_WEEK_NAME.search(orig)
        raw = (m.group("p") or m.group("p2")) if m else ""
        raw = re.sub(r"\b(?:last week|this week|week \d+)\b", "", raw, flags=re.I).strip()
        player = _player_for(raw, conv, ctx)
        if not player:
            return Plan(F_PLAYER_WEEK, APP_DATA, clarification="Which player?")
        args = {"player": player}
        if week:
            args["week"] = week
        return Plan(F_PLAYER_WEEK, APP_DATA, [ToolCall("explain_player_week", args)], week=week, subject=player)

    if _WEEK_REF.search(low) or (week is None and _WEEK_STATUS.search(low)):
        which = "current" if "this week" in low else "last_final"
        args = {"week": week} if week else {"which": which}
        if _WEEK_LINEUP.search(low):
            lineup_args = {"week": week} if week else {"which": which}
            notes = ["“Last week” means the most recent finalized week."] if "last week" in low and not week else []
            return Plan(F_WEEK_LINEUP, APP_DATA, [ToolCall("get_week_lineup", lineup_args)], week=week, notes=notes)
        if _WEEK_STATUS.search(low) or _WEEK_SUMMARY.search(low) or week:
            return Plan(F_WEEK, APP_DATA, [ToolCall("get_week", args)], week=week)

    if _SNAPSHOT.search(low):
        return Plan(F_SNAPSHOT, APP_DATA, [ToolCall("get_current_roster_standings", {})])
    if _GAINS.search(low):
        return Plan(F_GAINS, APP_DATA, [ToolCall("get_official_standings", {})])
    if _STRENGTHS.search(low):
        return Plan(F_STRENGTHS, APP_DATA, [ToolCall("get_official_standings", {})])
    if _STANDINGS.search(low):
        return Plan(F_STANDINGS, APP_DATA, [ToolCall("get_official_standings", {})])
    if _EMPTY.search(low):
        return Plan(F_EMPTY, APP_DATA, [ToolCall("get_lineup_report", {})])

    for pattern in _ELIGIBLE:
        m = pattern.search(orig)
        if m and not re.match(r"^(?:i|we|you|anyone|anybody|someone|somebody)$", m.group("p").strip().lower()):
            player = _player_for(m.group("p"), conv, ctx)
            target = parse_slot(m.group("rest")) or (conv.position if "this slot" in low or "that slot" in low else "")
            if not player:
                return Plan(F_ELIGIBLE, APP_DATA, clarification="Which player?")
            if not target:
                return Plan(F_ELIGIBLE, APP_DATA, subject=player, clarification=f"Which position for {player}?")
            return Plan(F_ELIGIBLE, APP_DATA, [ToolCall("check_slot_eligibility", {"player": player, "slot": target})],
                        position=target, subject=player)

    if _FIND_ELIGIBLE.search(low) and slot:
        return Plan(F_FIND_ELIGIBLE, APP_DATA,
                    [ToolCall("find_eligible_players", {"slot": slot, "bench_only": "bench" in low})], position=slot)
    if _LINEUP.search(low):
        return Plan(F_LINEUP, APP_DATA, [ToolCall("get_lineup_report", {})])
    if _WAIVER.search(low) and not _HOWTO.search(stripped):
        position = slot or (conv.position if followup else "")
        calls = [ToolCall("get_waiver_recommendations", {"position": position} if position else {}),
                 ToolCall("find_feature", {"task": "consider_add"})]
        # No shared waiver reader yet: the answer is page help, so it's grounded as such.
        return Plan(F_WAIVER, PRODUCT_HELP, calls, position=position)
    if _LEAGUE.search(low):
        return Plan(F_LEAGUE, APP_DATA, [ToolCall("get_active_league", {})])
    if followup and conv.intent in (F_GAINS, F_STRENGTHS, F_STANDINGS) and re.search(r"\bpoints?\b|\bcategor", low):
        return Plan(F_GAINS, APP_DATA, [ToolCall("get_official_standings", {})])
    return None
