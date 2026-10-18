"""Deterministic routing: question + page context + conversation → intent and tool plan.

Order matters and is the whole policy:

1. requests to *do* something (draft, add, drop, trade, set lineup) → refused, pointed at the UI;
2. questions needing live MLB information → "outside the app's data";
3. app help (capabilities, how-to, this page, metric definitions);
4. draft (read-only page snapshot) and fantasy-team (deferred to Phase C) questions;
5. stats: comparison, trend, valuation, leaderboard, player profile / seasons;
6. follow-ups reuse the previous subject; anything else gets a clarifying reply.

Players come from names in the question, then — for "he" / "this player" / elliptical
follow-ups — the conversation subject or the players selected on the page.
"""

from __future__ import annotations

import re
from typing import Any

from ami_assistant.capabilities import APP_DATA, EXTERNAL_CURRENT, PRODUCT_HELP
from ami_assistant.context import DRAFT_PAGES, AmiPageContext
from ami_assistant.conversation import ConversationState
from ami_assistant.data import BaseballDataset
from ami_assistant.fantasy_router import F_WAIVER, FANTASY_INTENTS, fantasy_plan
from ami_assistant.glossary import match_term
from ami_assistant.page_help import PAGE_HELP, find_draft_tools, find_howto, find_page
from ami_assistant.plans import Plan, ToolCall
from ami_assistant.players import (
    AMBIGUOUS,
    BASE_STOPWORDS,
    NOT_FOUND,
    RESOLVED,
    PlayerRef,
    Resolution,
    find_player_mentions,
    player_ref,
    resolve_label,
    resolve_player,
)

# Intents
ACTION = "action_request"
EXTERNAL = "external_current"
CAPABILITIES = "capabilities"
HELP_HOWTO = "help_howto"
HELP_PAGE = "help_page"
HELP_METRIC = "help_metric"
HELP_DRAFT_TOOLS = "help_draft_tools"
DRAFT_NEXT = "draft_next"
DRAFT_EXPLAIN = "draft_explain"
DRAFT_NEEDS = "draft_needs"
DRAFT_STRATEGY = "draft_strategy"
SLEEPERS = "sleepers"
FANTASY = "fantasy_team"
COMPARE = "compare"
TREND = "trend"
TREND_LEADERS = "trend_leaders"
VALUATION = "valuation"
VALUATION_BOARD = "valuation_board"
LEADERBOARD = "leaderboard"
PROFILE = "player_profile"
SEASONS = "player_seasons"
CLARIFY = "clarify"

STAT_INTENTS = frozenset({COMPARE, TREND, TREND_LEADERS, VALUATION, VALUATION_BOARD, LEADERBOARD, PROFILE, SEASONS})
RANKING_PAGES = ("Leaderboards", "Career Totals", "Historical Explorer")
RANKABLE = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
_YEAR = r"((?:18|19|20)\d{2})"

# Plain words → the app's stats. Longest phrases first so "home runs" isn't read as "runs".
STAT_WORDS: tuple[tuple[str, str], ...] = (
    ("on-base plus slugging", "OPS"), ("runs batted in", "RBI"), ("batting average", "BA"),
    ("on-base percentage", "OBP"), ("on base percentage", "OBP"), ("stolen bases", "SB"), ("stolen base", "SB"),
    ("home runs", "HR"), ("home run", "HR"), ("at-bats", "AB"), ("at bats", "AB"), ("on-base", "OBP"),
    ("slugging", "SLG"), ("homers", "HR"), ("steals", "SB"), ("doubles", "2B"), ("triples", "3B"), ("walks", "BB"),
    ("hits", "H"), ("runs", "R"), ("average", "BA"), ("ops", "OPS"), ("obp", "OBP"), ("slg", "SLG"), ("avg", "BA"),
    ("hrs", "HR"), ("hr", "HR"), ("rbis", "RBI"), ("rbi", "RBI"), ("sb", "SB"), ("ba", "BA"), ("bb", "BB"),
)
# A kind of hitter → the app stats used to measure it (named in the answer).
FOCUS_STATS: dict[str, tuple[str, ...]] = {
    "power": ("HR", "SLG", "2B"),
    "speed": ("SB", "3B"),
    "contact": ("BA", "H"),
    "patience": ("BB", "OBP"),
    "production": ("R", "RBI"),
}
FOCUS_WORDS: tuple[tuple[str, str], ...] = (
    ("run production", "production"), ("power", "power"), ("pop", "power"), ("slugger", "power"),
    ("speed", "speed"), ("faster", "speed"), ("contact", "contact"), ("patience", "patience"),
    ("discipline", "patience"), ("production", "production"),
)
POSITION_WORDS: tuple[tuple[str, str], ...] = (
    ("shortstops", "SS"), ("shortstop", "SS"), ("catchers", "C"), ("catcher", "C"),
    ("first basemen", "1B"), ("first baseman", "1B"), ("first base", "1B"),
    ("second basemen", "2B"), ("second baseman", "2B"), ("second base", "2B"),
    ("third basemen", "3B"), ("third baseman", "3B"), ("third base", "3B"),
    ("outfielders", "OF"), ("outfielder", "OF"), ("outfield", "OF"),
    ("designated hitters", "DH"), ("designated hitter", "DH"), ("pitchers", "P"),
    ("ss", "SS"), ("dh", "DH"),
)
POSITION_NAMES = {"SS": "shortstops", "C": "catchers", "1B": "first basemen", "2B": "second basemen",
                  "3B": "third basemen", "OF": "outfielders", "DH": "designated hitters", "P": "pitchers"}

ACTION_VERBS: tuple[tuple[str, str], ...] = (
    ("use suggested lineup", "use_suggested_lineup"), ("use the suggested lineup", "use_suggested_lineup"),
    ("finalize", "finalize_week"), ("lock", "change_lineup"),
    ("set my lineup", "change_lineup"), ("set the lineup", "change_lineup"), ("pick up", "add_waiver_player"),
    ("draft", "draft_player"), ("pick", "draft_player"), ("select", "draft_player"), ("take", "draft_player"),
    ("queue", "queue_player"), ("add", "add_waiver_player"), ("claim", "add_waiver_player"),
    ("drop", "drop_player"), ("release", "drop_player"), ("cut", "drop_player"),
    ("trade", "execute_trade"), ("propose", "execute_trade"), ("accept", "execute_trade"), ("execute", "execute_trade"),
    ("bench", "change_lineup"), ("start", "change_lineup"), ("sit", "change_lineup"), ("swap", "change_lineup"),
    ("save", "app_change"), ("delete", "app_change"), ("reset", "app_change"), ("undo", "app_change"),
)
_ACTION_LEAD = r"^(?:ami[,:]?\s+)?(?:please\s+|can you\s+|could you\s+|would you\s+|go ahead and\s+|now\s+)*"
_NAVIGATE = re.compile(r"^(?:please\s+)?(?:open|go to|take me to|navigate to|bring up|switch to)\s+(?P<target>.+?)(?:\s+page)?[?.!]?$")
_HOWTO = re.compile(
    r"^(?:how (?:do|can|would|should|could) (?:i|we|you)|how to|where (?:do|can|would|should) i|where(?:'s| is| are)"
    r"|show me how|steps to|walk me through|is there a way to)\b"
)
_DEFINITION = re.compile(r"^(?:what(?:'s| is| are| does| do)|whats|define|explain|meaning of|what do you mean by)\b")
# "Where did the full table go?" — redesigned pages keep advanced controls under Explore more.
_EXPLORE = re.compile(
    r"\b(?:explore more|advanced (?:filters?|controls?|options|settings|charts?|stats)|full (?:table|ranking|rankings|list|"
    r"standings)|detailed (?:table|filters?|stats|breakdown|charts?)|more (?:filters|options|details?|controls|settings)|"
    r"(?:filters?|tables?|charts?|controls|settings|scatter ?plots?|weights) (?:go|went|gone|moved))\b")
_EXPLORE_ASK = re.compile(r"\b(?:where|find|happened|under|went|gone|moved|see|show)\b")
_DRAFT_TOOLS_ASK = re.compile(r"\bdraft (?:tools?|pages?|options|choices)\b|\bwhich draft (?:tool|page)\b")
# "How is Live Draft different?", "What is Draft Lab for?": a question about one draft tool itself.
_DRAFT_TOOL_EXPLAIN = re.compile(
    r"\b(?:different|difference|differs?|compare[ds]?|comparison|versus|vs\.?|instead of|better than|"
    r"when (?:should|would|do) i use|why (?:would|should) i use|should i use)\b|\bwhat(?:'s| is| are)\b.*\bfor\b"
    r"|\bwhat does\b.*\bdo\b")
# Requests for the active draft's picks always go to draft intelligence, whichever tool is named.
_ACTIVE_DRAFT = re.compile(
    r"\bwho should i (?:draft|take|pick|target)\b|\bdraft next\b|\bnext pick\b|\bon the clock\b|\brecommend|"
    r"\bbest (?:available|pick)\b|\bmy (?:team|roster)(?:'s)? needs?\b|\bwhy is\b.*\brecommended\b")
_FOLLOW_ON = re.compile(r"^(?:what about|how about|and\b|or\b|ok(?:ay)?\b|now\b)|\bit\b")
# "What does Draft mean on my lineup?" — the Lineup page's status, not drafting players.
_LINEUP_STATUS = re.compile(r"\b(?:not saved|saved and locked|not submitted|lineup status)\b"
                            r"|\bdraft\b.*\blineup\b|\blineup\b.*\bdraft\b")
_MEANING = re.compile(r"\bmean(?:s|ing)?\b|^(?:what(?:'s| is| are| does)|whats|explain)\b")
_PROJECTION = re.compile(r"\b(?:project(?:s|ed|ion|ions)?|forecast\w*|predict(?:s|ed|ion|ions)?|next season|next year)\b")
_CAPABILITIES = re.compile(r"\b(?:what can you (?:do|answer|help)|what do you know|who are you|what are you|what should i ask)\b|^help$")
_PAGE_TASKS = re.compile(r"\bwhat (?:can|should|do) i (?:do|see|find|use) (?:on|in)\b")
_PAGE_HELP = re.compile(r"\b(?:this page|this screen|this chart|this table|this tool|am i looking at|i'm looking at|on here|(?:do|see|find|start) here)\b")
_EXTERNAL = re.compile(
    r"\b(?:today|tonight|yesterday|right now|currently|so far this (?:season|year)|this (?:season|year)|live score"
    r"|injur(?:y|ed|ies)|news|rumou?rs?|trade deadline|on the il|box score|(?:al|nl|mlb) standings"
    r"|standings in (?:the )?(?:al|nl|mlb))\b"
)
_SELF = re.compile(r"\b(?:my|our) (?:team|roster|lineup|league|bench|standings)\b")
_PRONOUN = re.compile(r"\b(?:he|him|his|she|her|they|them|their|both|this player|that player|these players|this guy|the two)\b")
_PLURAL_PRONOUN = re.compile(r"\b(?:they|them|their|both|these players|the two|of them|between them)\b")
_FOLLOWUP = re.compile(r"^(?:what about|how about|and\b|ok(?:ay)?\b|now\b|same\b|just\b|only\b|instead\b)|\b(?:instead|just the|only the)\b")
_COMPARE_WORD = re.compile(r"\b(?:compare|comparison|versus|vs\.?)(?![a-z])")
_COMPARATIVE = re.compile(r"\b(?:better|more|higher|lower|fewer|less|which (?:one|player|of them))\b")
_SUPERLATIVE = re.compile(r"\b(?:best|top|most|highest|lowest|leaders?|led|leads|leading|greatest|worst|fewest|rank(?:ed|ing|s)?)\b")
_BEST_SEASONS = re.compile(r"\b(?:best|top|greatest|worst) (?:seasons?|years?)\b")
_TREND = re.compile(
    r"\b(?:trend|trends|trending|trajectory|improv\w*|declin\w*|chang(?:ed|ing)|over time|getting (?:better|worse)"
    r"|breakout|fading|slope)\b"
)
_VALUE = re.compile(r"\b(?:valuation|undervalued|overvalued|value score|valued|best values?)\b")
_DRAFT = re.compile(
    r"\b(?:draft|drafting|next pick|on the clock|best available|bpa|best player available|recommend\w*|decision score|reach)\b"
)
_NEEDS = re.compile(r"\b(?:weak|weakest|need|needs|missing|holes?|lacking|short at|strengths?)\b")
_FANTASY = re.compile(
    r"\b(?:waivers?|waiver wire|free agents?|drop|trade|trades|lineup|start this week|start or sit|start/sit|standings"
    r"|bench|categories am i|i need an? )"
)
_PROFILE = re.compile(r"\b(?:career|stats|numbers|tell me about|who (?:is|was)|show me|how good|profile|seasons?)\b")
_RANKED_HIGH = re.compile(
    r"\branked (?:this|so|that) (?:high|low)|\bwhy is (?:he|she|this player) (?:ranked|rated|so high|so low|here)"
    r"|\bwhy (?:is|does) (?:he|she|this player) rank"
)
_COMPARE_SLOTS = (
    re.compile(r"\bcompare (.+?) (?:and|with|to|vs\.?|versus) (.+?)(?=$|[?.!,]| over | from | in | since | for | during | between | on | across )", re.I),
    re.compile(r"^(?:who was better[,:]? )?(.+?) (?:vs\.?|versus) (.+?)(?=$|[?.!,]| over | from | in | since | for )", re.I),
)


def _low(text: str) -> str:
    return " " + re.sub(r"\s+", " ", str(text or "").lower().replace("’", "'")).strip() + " "


def _n(word: str) -> int:
    return NUMBER_WORDS.get(word, 0) or int(word)


def parse_years(text: str, latest: int) -> tuple[tuple[int, int] | None, int | None, bool]:
    """(season range, trailing window, explicitly whole-career) from the question."""
    low = _low(text)
    m = re.search(rf"{_YEAR}\s*(?:-|–|—|to|through|thru|and|until)\s*{_YEAR}", low)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b)), None, False
    m = re.search(rf"\bsince {_YEAR}", low)
    if m:
        return (int(m.group(1)), max(latest, int(m.group(1)))), None, False
    m = re.search(rf"\b(?:last|past|previous|recent)\s+{_NUM}\s+(?:years|seasons)", low) or re.search(
        rf"\b{_NUM}[- ](?:year|season)\b", low
    )
    if m:
        n = max(1, min(_n(m.group(1)), 30))
        return (latest - n + 1, latest), n, False
    if re.search(r"\b(?:last|past|previous) (?:year|season)\b", low):
        return (latest, latest), 1, False
    m = re.search(rf"\b{_YEAR}\b", low)
    if m:
        y = int(m.group(1))
        return (y, y), None, False
    career = bool(re.search(r"\b(?:career|careers|all[- ]time|ever|lifetime)\b", low))
    return None, None, career


def parse_stats(text: str) -> tuple[list[str], str]:
    """App stats named in the text (in order) and an optional hitter "focus" word."""
    low = _low(text)
    found: list[str] = []
    for phrase, code in STAT_WORDS:
        pat = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
        if re.search(pat, low):
            if code not in found:
                found.append(code)
            low = re.sub(pat, " ", low)
    focus = next((f for word, f in FOCUS_WORDS if re.search(rf"\b{re.escape(word)}\b", _low(text))), "")
    return found, focus


def parse_position(text: str) -> str:
    low = _low(text)
    for phrase, code in POSITION_WORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", low):
            return code
    return ""


def _page_words() -> frozenset[str]:
    words = set()
    for p in PAGE_HELP.values():
        for name in (p.key, *p.aliases):
            words.update(w.lower() for w in re.findall(r"[A-Za-z]+", name))
    return frozenset(words)


PAGE_WORDS = _page_words()


def detect_action(text: str) -> str:
    """A request for AMI to change something (draft, add, drop, trade, lineup, save…)."""
    low = _low(text).strip()
    # "Draft Lab …", "Trade Center …" name a page, not an instruction.
    if any(low.startswith(name) for p in PAGE_HELP.values() for name in (p.key.lower(), *p.aliases)
           if " " in name):
        return ""
    if re.match(_ACTION_LEAD + r"take me\b", low):
        return ""
    for verb, action in ACTION_VERBS:
        if re.match(_ACTION_LEAD + re.escape(verb) + r"\b", low):
            return action
    if re.search(r"\b(?:for me|on my behalf)\b", low):
        for verb, action in ACTION_VERBS:
            if re.search(rf"\b{re.escape(verb)}\b", low):
                return action
    return ""


class Router:
    def __init__(self, dataset: BaseballDataset | None) -> None:
        self.ds = dataset

    # ---- players -------------------------------------------------------------------
    def _context_players(self, ctx: AmiPageContext) -> list[PlayerRef]:
        if self.ds is None:
            return []
        out = []
        for label in ctx.players:
            res = resolve_label(self.ds, label)
            if res.status == RESOLVED and res.player and res.player not in out:
                out.append(res.player)
        return out

    def _conversation_players(self, conv: ConversationState) -> list[PlayerRef]:
        if self.ds is None:
            return []
        return [player_ref(self.ds, pid) for pid in conv.player_ids if pid in self.ds.players.index]

    @staticmethod
    def _unclear(text: str, res: Resolution) -> str:
        if res.status == AMBIGUOUS:
            options = "; ".join(c.label for c in res.candidates[:5])
            return f"More than one player matches “{text}”: {options}. Which one do you mean?"
        near = ", ".join(c.label for c in res.candidates[:3])
        return f"I couldn't find “{text}” in the app's data." + (f" Did you mean {near}?" if near else "")

    def _mentions(self, question: str, ctx_ids: list[str]) -> tuple[list[PlayerRef], list[str], str]:
        """Resolved players in the question, interpretation notes, and a clarification if a name is unclear."""
        if self.ds is None:
            return [], [], ""
        players: list[PlayerRef] = []
        notes: list[str] = []
        for m in find_player_mentions(self.ds, question, prefer_ids=ctx_ids, extra_stopwords=PAGE_WORDS):
            res = m.resolution
            if res.status == RESOLVED and res.player:
                if res.player not in players:
                    players.append(res.player)
                if res.note:
                    notes.append(res.note)
            else:
                return [], [], self._unclear(m.text, res)
        # Names in "compare X and Y" / "X vs Y" slots must each resolve — this is how an
        # unknown name ("Compare Judge and Smithers") is caught instead of ignored.
        for pattern in _COMPARE_SLOTS:
            m = pattern.search(str(question or "").strip())
            if not m:
                continue
            for slot in (m.group(1), m.group(2)):
                slot = re.sub(r"^(?:the |players? )", "", slot.strip(), flags=re.I)
                if not slot or any(p.name.lower() in slot.lower() or slot.lower() in p.name.lower() for p in players):
                    continue
                words = re.findall(r"[a-z]+", slot.lower())
                if re.search(r"\d", slot) or not words or all(w in BASE_STOPWORDS or w in PAGE_WORDS for w in words):
                    continue  # "over 2020", "each other", "them" — not a name
                res = resolve_player(self.ds, slot, prefer_ids=ctx_ids)
                if res.status == RESOLVED and res.player:
                    players.append(res.player)
                    if res.note:
                        notes.append(res.note)
                else:
                    return [], [], self._unclear(slot, res)
            break
        return players, notes, ""

    # ---- main ----------------------------------------------------------------------
    def route(self, question: str, ctx: AmiPageContext, conv: ConversationState) -> Plan:
        q = str(question or "").strip()
        low = _low(q)
        latest = self.ds.latest_season if self.ds else 0
        if not q:
            return Plan(CLARIFY, PRODUCT_HELP, clarification="Ask me about a player, a page, or a stat.")

        action = detect_action(q)
        if action:
            return self._action_plan(q, action)

        # "Open Fantasy Standings" / "Take me to Waiver Wire": AMI explains where it is (it doesn't navigate).
        nav = _NAVIGATE.match(low.strip())
        if nav and find_page(nav.group("target")) is not None:
            page = find_page(nav.group("target"))
            return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": page.key})], page=page.key)

        # "What can I do on Home?" names the page it's about.
        named = find_page(q) if _PAGE_TASKS.search(low) else None
        if named is not None:
            return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": named.key})], page=named.key)

        help_plan = self._ui_help_plan(q, low, ctx, conv)
        if help_plan is not None:
            return help_plan

        # League questions before the live-MLB check: "how would my current roster rank right now?"
        # is about the user's league, not today's MLB.
        fplan = fantasy_plan(q, ctx, conv)
        if fplan is not None:
            return fplan

        year_range, window, career = parse_years(q, latest) if self.ds else (None, None, False)
        if self.ds and year_range and year_range[0] > latest:
            return Plan(EXTERNAL, EXTERNAL_CURRENT, year_range=year_range)
        if _EXTERNAL.search(low) and not _SELF.search(low) and not _PAGE_HELP.search(low):
            return Plan(EXTERNAL, EXTERNAL_CURRENT)

        # Projections live on ML Predictions, which AMI can't read yet. Never answer a "next season"
        # question with historical numbers.
        if _PROJECTION.search(low) and not _HOWTO.search(low.strip()) and not _DEFINITION.search(low.strip()):
            return Plan(CLARIFY, APP_DATA, page="ML Predictions", clarification=(
                "AMI can't read the app's projections yet, so it won't guess next-season numbers from past seasons. "
                "Open **ML Predictions** (under Insights) for the model's next-season projections."))

        if _CAPABILITIES.search(low.strip()):
            return Plan(CAPABILITIES, PRODUCT_HELP)
        if _HOWTO.search(low.strip()):
            return self._howto_plan(q, ctx)

        ctx_players = self._context_players(ctx)
        mentioned, notes, unclear = self._mentions(q, [p.player_id for p in ctx_players])

        if _PAGE_HELP.search(low) and not mentioned and not unclear and not _RANKED_HIGH.search(low) and not _TREND.search(low):
            if ctx.page not in PAGE_HELP:
                return Plan(CLARIFY, PRODUCT_HELP, clarification="Which page do you mean? Open it and ask again, or name it.")
            return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": ctx.page})], page=ctx.page,
                        used_context=["page"])

        if _DEFINITION.search(low.strip()) and not mentioned and not unclear and not _SUPERLATIVE.search(low) \
                and not _PRONOUN.search(low):
            term, term_len = match_term(q)
            page = find_page(q)
            # "What does Valuation mean?" names a page; "What does Valuation Score mean?" a metric.
            words = " " + re.sub(r"[^a-z0-9]+", " ", low) + " "
            page_named = page is not None and len(page.key) >= term_len and any(
                f" {re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()} " in words for name in (page.key, page.label))
            if term is not None and not page_named:
                return Plan(HELP_METRIC, PRODUCT_HELP, [ToolCall("explain_metric", {"term": term.key})])
            if page is not None:
                return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": page.key})], page=page.key)

        if unclear:
            return Plan(CLARIFY, APP_DATA, clarification=unclear)

        position = parse_position(q)
        plan = self._draft_or_fantasy(q, low, ctx, conv, mentioned, position)
        if plan is not None:
            plan.notes = notes + plan.notes
            return plan

        stats, focus = parse_stats(q)
        return self._stats_plan(low, ctx, conv, ctx_players, mentioned, notes, year_range, window, career,
                                stats, focus, position)

    # ---- help / actions ------------------------------------------------------------
    @staticmethod
    def _ui_help_plan(q: str, low: str, ctx: AmiPageContext, conv: ConversationState) -> Plan | None:
        """Questions about the redesigned UI itself: the draft tools, Explore more, lineup status."""
        tools = find_draft_tools(q)
        if not _ACTIVE_DRAFT.search(low):
            if _DRAFT_TOOLS_ASK.search(low) or len(tools) >= 2:
                return Plan(HELP_DRAFT_TOOLS, PRODUCT_HELP,
                            [ToolCall("explain_draft_tools", {"pages": tools if len(tools) >= 2 else []})])
            # One tool, asked about as a tool ("How is Live Draft different?"), or a follow-up to a
            # draft-tools answer ("What about Draft Lab?"): that tool first, the others for contrast.
            last = conv.turns[-1].intent if conv.turns else ""
            if len(tools) == 1 and (_DRAFT_TOOL_EXPLAIN.search(low) or (last == HELP_DRAFT_TOOLS and _FOLLOW_ON.search(low.strip()))):
                return Plan(HELP_DRAFT_TOOLS, PRODUCT_HELP, [ToolCall("explain_draft_tools", {"focus": tools[0]})])
        if _EXPLORE.search(low) and _EXPLORE_ASK.search(low):
            page = find_page(q)
            used = []
            if page is None and ctx.page in PAGE_HELP:
                page, used = PAGE_HELP[ctx.page], ["page"]
            if page is None:
                return Plan(HELP_METRIC, PRODUCT_HELP, [ToolCall("explain_metric", {"term": "explore_more"})])
            return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": page.key})], page=page.key,
                        focus="explore_more", used_context=used)
        if _LINEUP_STATUS.search(low) and _MEANING.search(low.strip()):
            return Plan(HELP_METRIC, PRODUCT_HELP, [ToolCall("explain_metric", {"term": "lineup_status"})])
        return None

    @staticmethod
    def _action_plan(q: str, action: str) -> Plan:
        howto = find_howto(q)
        page = find_page(q)
        if howto is not None:
            return Plan(ACTION, PRODUCT_HELP, [ToolCall("find_feature", {"task": howto.key})], action=action, page=howto.page)
        if page is not None:
            return Plan(ACTION, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": page.key})], action=action, page=page.key)
        return Plan(ACTION, PRODUCT_HELP, action=action)

    @staticmethod
    def _howto_plan(q: str, ctx: AmiPageContext) -> Plan:
        howto = find_howto(q)
        if howto is not None:
            return Plan(HELP_HOWTO, PRODUCT_HELP, [ToolCall("find_feature", {"task": howto.key})], page=howto.page)
        page = find_page(q)
        if page is None and _PAGE_HELP.search(_low(q)) and ctx.page in PAGE_HELP:
            page = PAGE_HELP[ctx.page]
        if page is not None:
            return Plan(HELP_PAGE, PRODUCT_HELP, [ToolCall("explain_app_page", {"page": page.key})], page=page.key)
        return Plan(CLARIFY, PRODUCT_HELP, clarification=(
            "I don't have step-by-step help for that yet. Try “How do I compare players?”, "
            "“Where do I make a trade?” or “How do I use Trend Value?”"
        ))

    # ---- draft / fantasy -----------------------------------------------------------
    def _draft_or_fantasy(
        self, q: str, low: str, ctx: AmiPageContext, conv: ConversationState, mentioned: list[PlayerRef], position: str
    ) -> Plan | None:
        on_draft_page = ctx.page in DRAFT_PAGES
        if re.search(r"\b(?:sleepers?|busts?)\b", low) and not mentioned:
            return Plan(SLEEPERS, APP_DATA, [ToolCall("get_sleepers_busts", {})])
        draftish = bool(_DRAFT.search(low)) or (on_draft_page and bool(
            re.search(r"\b(?:who should i (?:take|pick|draft)|recommended|this pick|i need an?)\b", low)
            or (_NEEDS.search(low) and re.search(r"\b(?:i|my|me)\b", low))
        ))
        if draftish:
            if re.search(r"\bneed\b.*\b(?:best (?:player )?available|bpa)\b|\b(?:best (?:player )?available|bpa)\b.*\bneed\b", low):
                return Plan(DRAFT_STRATEGY, APP_DATA,
                            [ToolCall("get_team_needs", {}), ToolCall("get_draft_recommendations", {"limit": 5})])
            if _NEEDS.search(low) and re.search(r"\b(?:position|positions|roster|categor\w*|team)\b", low) and not position:
                return Plan(DRAFT_NEEDS, APP_DATA, [ToolCall("get_team_needs", {})])
            if re.search(r"\bwhy\b", low) or (mentioned and re.search(r"\b(?:should i|good pick|recommended)\b", low)):
                who = mentioned[0].name if mentioned else ""
                if not who and conv.player_names and _PRONOUN.search(low):
                    who = conv.player_names[0]
                calls = [ToolCall("explain_draft_recommendation", {"player": who})] if who else [
                    ToolCall("get_draft_recommendations", {"limit": 1})]
                notes = [] if who else ["No player was named, so this explains the top recommendation."]
                return Plan(DRAFT_EXPLAIN, APP_DATA, calls, players=mentioned[:1], notes=notes)
            args: dict[str, Any] = {"limit": 5}
            if position:
                args["position"] = position
            return Plan(DRAFT_NEXT, APP_DATA, [ToolCall("get_draft_recommendations", args)], position=position)
        positions_need = _NEEDS.search(low) and re.search(r"\bpositions?\b", low) and re.search(r"\b(?:i|my)\b", low)
        if positions_need:
            return Plan(DRAFT_NEEDS, APP_DATA, [ToolCall("get_team_needs", {})])
        if _FANTASY.search(low) or (_SELF.search(low) and not mentioned):
            # League questions the fantasy router didn't recognize ("Who should I drop?", "I need a
            # shortstop"): roster moves are Waiver Wire territory. Its recommendations, plus the steps
            # (AMI never makes the move).
            howto = find_howto(q) or find_howto("waivers")
            calls = [ToolCall("get_waiver_recommendations", {"position": position} if position else {})]
            if howto:
                calls.append(ToolCall("find_feature", {"task": howto.key}))
            return Plan(F_WAIVER, APP_DATA, calls, position=position)
        return None

    # ---- stats ---------------------------------------------------------------------
    def _stat_intent(
        self, low: str, ctx: AmiPageContext, conv: ConversationState, mentioned: list[PlayerRef],
        subject_count: int, followup: bool, stats: list[str], position: str,
    ) -> str:
        if _RANKED_HIGH.search(low):
            by_page = {"Valuation": VALUATION, "Trend Value": TREND, "Leaderboards": LEADERBOARD, "Career Totals": LEADERBOARD}
            return by_page.get(ctx.page, conv.intent if conv.intent in STAT_INTENTS else VALUATION)
        if _VALUE.search(low):
            return VALUATION
        if _TREND.search(low):
            return TREND
        if _COMPARE_WORD.search(low) or len(mentioned) >= 2:
            return COMPARE
        if _COMPARATIVE.search(low) and not _SUPERLATIVE.search(low):
            return COMPARE
        if _SUPERLATIVE.search(low) and _PLURAL_PRONOUN.search(low) and subject_count >= 2:
            return COMPARE  # "who had the best OPS of them?"
        if _SUPERLATIVE.search(low) and not _BEST_SEASONS.search(low) and not (_PRONOUN.search(low) and not position) \
                and (position or stats or re.search(r"\b(?:who|players?|hitters?|leaders?)\b", low)):
            return LEADERBOARD
        if mentioned or _PROFILE.search(low) or _BEST_SEASONS.search(low):
            return PROFILE
        if followup and conv.intent in STAT_INTENTS:
            return conv.intent
        return ""

    def _stats_plan(
        self,
        low: str,
        ctx: AmiPageContext,
        conv: ConversationState,
        ctx_players: list[PlayerRef],
        mentioned: list[PlayerRef],
        notes: list[str],
        year_range: tuple[int, int] | None,
        window: int | None,
        career: bool,
        stats: list[str],
        focus: str,
        position: str,
    ) -> Plan:
        conv_players = self._conversation_players(conv)
        pronoun = bool(_PRONOUN.search(low))
        followup = not mentioned and bool(conv.intent) and (
            bool(_FOLLOWUP.search(low.strip())) or pronoun or bool(_COMPARATIVE.search(low)) or bool(year_range)
            or bool(focus) or career
        )
        subject_count = len(mentioned) or (len(conv_players) if followup else len(ctx_players))
        intent = self._stat_intent(low, ctx, conv, mentioned, subject_count, followup, stats, position)
        if not intent:
            return Plan(CLARIFY, APP_DATA, notes=notes, clarification=(
                "I can answer from the app's data or explain how to use it. Try “Compare Aaron Judge and Juan Soto”, "
                "“Who led in OPS from 2022 to 2025?”, “How has Mookie Betts's power changed?” or "
                "“What does Decision Score mean?”"
            ))

        used: list[str] = []
        players = list(mentioned)
        # "Who is improving fastest?" / "Who are the best values?" want a list, not the selected player.
        list_question = not pronoun and bool(re.search(
            r"^\s*(?:who|which (?:players?|hitters?))\b|\b(?:fastest|biggest|most improved|best values?|top values?)\b", low))
        if not players and intent != LEADERBOARD and not (intent in (TREND, VALUATION) and list_question):
            # "he"/"this player"/follow-ups: the last answer's subject if it came from this page,
            # otherwise the players selected on the page.
            if (pronoun or followup) and conv_players and (conv.page == ctx.page or not ctx_players):
                players = conv_players
                used.append("conversation")
            elif ctx_players:
                players = ctx_players
                used.append("page selection")
            elif conv_players and (pronoun or followup):
                players = conv_players
                used.append("conversation")
        if not year_range and not career and followup and conv.year_range and intent in (COMPARE, SEASONS, LEADERBOARD):
            year_range = (int(conv.year_range[0]), int(conv.year_range[1]))
            used.append("conversation range")
        if not year_range and not career and re.search(r"\b(?:this|that|the same) (?:range|window|period)\b", low) and ctx.year_range:
            year_range = ctx.year_range
            used.append("page range")
        if not stats and not focus and followup and conv.stats and intent in (COMPARE, LEADERBOARD):
            stats = list(conv.stats)
        if not position and followup and conv.position and intent == LEADERBOARD:
            position = conv.position

        plan = Plan(intent, APP_DATA, players=players, year_range=year_range, window=window,
                    stats=stats or list(FOCUS_STATS.get(focus, ())), focus=focus, position=position,
                    notes=list(notes), used_context=used)
        return self._fill_stat_calls(plan, low, ctx, career)

    def _fill_stat_calls(self, plan: Plan, low: str, ctx: AmiPageContext, career: bool) -> Plan:
        latest = self.ds.latest_season if self.ds else 0
        ids = [p.player_id for p in plan.players]

        if plan.intent == COMPARE:
            if len(ids) >= 2:
                args: dict[str, Any] = {"player_ids": ids[:3]}
                if plan.year_range:
                    args["year_range"] = list(plan.year_range)
                if plan.stats:
                    args["stats"] = plan.stats
                plan.calls = [ToolCall("compare_players", args)]
                return plan
            if not ids:
                return Plan(CLARIFY, APP_DATA, clarification="Which players should I compare? Name two (or three).")
            plan.intent = SEASONS if plan.year_range else PROFILE

        if plan.intent in (TREND, VALUATION) and len(ids) > 1:
            if _PLURAL_PRONOUN.search(low) or len(ids) == 2 and not _PRONOUN.search(low):
                plan.players, ids = plan.players[:2], ids[:2]
            else:
                names = " or ".join(p.name for p in plan.players[:3])
                return Plan(CLARIFY, APP_DATA, clarification=f"Which player — {names}?")

        window = plan.window or ctx.window or 3
        if plan.intent in (TREND, VALUATION) and plan.year_range and not plan.window:
            if plan.year_range[1] == latest and plan.year_range[0] < latest:
                window = plan.year_range[1] - plan.year_range[0] + 1
            else:
                plan.notes.append(f"Trend Value and Valuation look at trailing seasons ending in {latest}; this uses the last {window}.")
        min_games = ctx.min_games if ctx.min_games is not None and ctx.page in ("Trend Value", "Valuation") else 50

        if plan.intent == TREND:
            plan.window = window
            if not ids:
                stat = (plan.stats or ([ctx.metric] if ctx.metric in RANKABLE else []) or ["OPS"])[0]
                direction = "declining" if re.search(r"\b(?:declin\w*|fading|worse|dropping)\b", low) else "improving"
                plan.intent = TREND_LEADERS
                plan.stats = [stat]
                plan.calls = [ToolCall("get_trend_leaders", {"stat": stat, "window": window, "min_games": min_games,
                                                             "direction": direction})]
                return plan
            args = {"window": window, "min_games": min_games}
            if plan.stats:
                args["stats"] = plan.stats
            plan.calls = [ToolCall("get_player_trends", {"player_id": pid, **args}) for pid in ids[:2]]
            return plan

        if plan.intent == VALUATION:
            plan.window = window
            args = {"window": window, "min_games": min_games}
            if ctx.page == "Valuation":
                if ctx.weight_current is not None:
                    args["weight_current"] = ctx.weight_current
                if ctx.weight_trend is not None:
                    args["weight_trend"] = ctx.weight_trend
            if not ids:
                plan.intent = VALUATION_BOARD
                plan.calls = [ToolCall("get_player_valuation", {**args, "top_n": 10})]
            else:
                plan.calls = [ToolCall("get_player_valuation", {"player_id": pid, **args}) for pid in ids[:2]]
            return plan

        if plan.intent == LEADERBOARD:
            stat = (plan.stats or [""])[0]
            if not stat and ctx.page in RANKING_PAGES and ctx.metric in RANKABLE:
                stat = ctx.metric
                plan.used_context.append("page stat")
                plan.notes.append(f"Ranked by {stat}, the stat this page is sorted by; ask for another stat to re-rank.")
            if not stat:
                stat = "OPS"
                plan.notes.append("Ranked by OPS (on-base plus slugging); ask for HR, RBI, SB or another stat to re-rank.")
            rng = plan.year_range
            if rng is None and not career:
                if ctx.year_range and ctx.page in RANKING_PAGES:
                    rng = ctx.year_range
                    plan.used_context.append("page range")
                else:
                    page = "Career Totals" if plan.position else "Leaderboards"
                    rng = (2010, latest) if plan.position else (2020, latest)  # those pages' default ranges
                    plan.notes.append(f"No seasons given, so this uses the {page} page's default range, {rng[0]}–{rng[1]}.")
            args = {"stat": stat, "top_n": 10}
            if rng:
                args["year_range"] = list(rng)
            if plan.position:
                args["position"] = plan.position
                if ctx.page == "Career Totals" and ctx.position_mode.startswith("Season"):
                    args["position_mode"] = "season"
            if plan.players:
                args["focus_player_id"] = plan.players[0].player_id
            plan.year_range = rng
            plan.stats = [stat]
            plan.calls = [ToolCall("get_leaderboard", args)]
            return plan

        if plan.intent in (PROFILE, SEASONS):
            if not ids:
                return Plan(CLARIFY, APP_DATA, clarification="Which player? Name them, or select one on the page.")
            if len(ids) > 1 and _PRONOUN.search(low) and not _PLURAL_PRONOUN.search(low):
                names = " or ".join(p.name for p in plan.players[:3])
                return Plan(CLARIFY, APP_DATA, clarification=f"Which player — {names}?")
            pid = ids[0]
            plan.players = plan.players[:1]
            if plan.year_range and not _BEST_SEASONS.search(low):
                plan.intent = SEASONS
                plan.calls = [ToolCall("get_player_seasons", {"player_id": pid, "year_range": list(plan.year_range)})]
            else:
                plan.intent = PROFILE
                plan.calls = [ToolCall("get_player_profile", {"player_id": pid})]
            return plan
        return Plan(CLARIFY, APP_DATA, clarification="Could you rephrase that?")
