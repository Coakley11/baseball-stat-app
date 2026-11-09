"""A1: AMI reads the user's own saved Draft Strategies and Global Queue (read-only).

Strictly read-only:
* Strategies are read through ``draft_strategy_v2.list_strategies_v2`` / ``research_log`` and the store's
  own access check (``draft_strategy_store._require_access``: signed in, and the same Pro entitlement as
  the page). Storage is account-scoped, so only the signed-in account's rows are ever visible.
* Nothing here writes to storage or to the session. Session values are only read with ``.get``. The tools
  never call helpers that create session keys (``draft_strategy_work._work``), purge the trash
  (``list_trash``) or drop the Global Queue's "loaded from" record (``reconcile_loaded_strategy``); the
  live check for that record is done here without changing anything.
* Deleted strategies are never read: they live in a separate item type (``draft_strategy_trash``),
  which these tools never open.
* Saved data and unsaved editor changes are returned separately (``saved`` / ``unsaved``), so answers can
  keep them apart.
* The Global Queue is a Free feature, so ``get_global_list`` declares no plan capability. The strategy
  tools declare ``draft_strategy_library``, the same capability as the strategy page (registry gate).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ami_assistant.safety import clean_text
from ami_assistant.tools.registry import INTERNAL_ERROR, NOT_ENTITLED, ToolResult, fail, tool

CAPABILITY = "my_strategies"
PLAN_CAPABILITY = "draft_strategy_library"  # baseball_monetization.CAPABILITY_FEATURES → DRAFT_STRATEGIES
SIGN_IN_REQUIRED = "sign_in_required"
NO_STRATEGIES = "no_strategies"
WHICH_STRATEGY = "which_strategy"
UNKNOWN_STRATEGY = "unknown_strategy"
STORAGE_UNAVAILABLE = "storage_unavailable"

RESEARCH_LIMIT = 20
NAME_LIMIT = 60
NOTE_LIMIT = 500
_NAME_NOISE = re.compile(r"\b(?:strateg(?:y|ies)|plan|queue|the|my)\b")
_SUFFIX = re.compile(r"\b(?:jr|sr|ii|iii|iv)\b")
ELSEWHERE_LIMIT = 5


def player_key(name: Any) -> str:
    """Case, punctuation and Jr./Sr. ignored ("Bobby Witt Jr." == "bobby witt jr")."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower().replace("’", "'").replace("'", ""))
    return " ".join(_SUFFIX.sub(" ", text).split())


def find_entry(subject: str, entries: list[dict[str, Any]], question: str = "") -> dict[str, Any] | None:
    """The entry the user named: the full name, then a unique last or partial name; else an entry whose
    full name appears in the question. Never a guess between several players."""
    want = player_key(subject)
    keyed = [(e, player_key(e.get("name"))) for e in entries]
    if want:
        exact = [e for e, k in keyed if k == want]
        if exact:
            return exact[0]
        partial = [e for e, k in keyed if k and (f" {want} " in f" {k} " or k.split()[-1:] == want.split()[-1:])]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            return None
    q = f" {player_key(question)} "
    named = [e for e, k in keyed if k and f" {k} " in q]
    return named[0] if len(named) == 1 else None


# --- read-only session access ------------------------------------------------------------------


def _work_records(session: Mapping[str, Any]) -> dict[str, Any]:
    import draft_strategy_work as work

    recs = session.get(work.WORK_KEY)
    return recs if isinstance(recs, dict) else {}


def _open_id(session: Mapping[str, Any]) -> str:
    import draft_strategy_work as work

    return str(session.get(work.OPEN_KEY) or "")


def _access_error(session: Mapping[str, Any], tool_name: str) -> ToolResult | None:
    import draft_strategy_store as store

    try:
        store._require_access(session)  # the page's own check: signed in + the Pro entitlement
    except store.StrategyError as exc:
        text = str(exc)
        code = SIGN_IN_REQUIRED if "Sign in" in text else NOT_ENTITLED
        return fail(tool_name, code, text)
    return None


def _live(session: Mapping[str, Any], tool_name: str) -> tuple[list[dict[str, Any]] | None, ToolResult | None]:
    """Live (not deleted) strategies of this account, upgraded in memory (never written)."""
    import draft_strategy_store as store
    import draft_strategy_v2 as v2

    blocked = _access_error(session, tool_name)
    if blocked is not None:
        return None, blocked
    try:
        rows = v2.list_strategies_v2(session)  # type: ignore[arg-type]
    except store.StrategyError as exc:
        return None, fail(tool_name, STORAGE_UNAVAILABLE, str(exc))
    return [r for r in rows if isinstance(r, dict) and r.get("id")], None


# --- shaping ---------------------------------------------------------------------------------


def _entries(strategy: Mapping[str, Any]) -> list[dict[str, Any]]:
    notes = strategy.get("notes") if isinstance(strategy.get("notes"), dict) else {}
    pins = {str(p) for p in strategy.get("pins") or []}
    out = []
    for rank, e in enumerate(strategy.get("queue") or [], start=1):
        if not isinstance(e, dict):
            continue
        name = clean_text(e.get("name"), NAME_LIMIT)
        if not name:
            continue
        key = name.lower()
        note = notes.get(key) if isinstance(notes.get(key), dict) else {}
        out.append({"rank": rank, "name": name, "position": clean_text(e.get("position"), 20),
                    "team": clean_text(e.get("team"), 10), "pinned": key in pins,
                    "note": clean_text(note.get("text"), NOTE_LIMIT),
                    "note_source": clean_text(note.get("source"), 20)})
    return out


def _view(strategy: Mapping[str, Any]) -> dict[str, Any]:
    prefs = strategy.get("preferences") if isinstance(strategy.get("preferences"), dict) else {}
    return {
        "name": clean_text(strategy.get("name"), NAME_LIMIT),
        "approach": clean_text(strategy.get("approach"), 30),
        "preferences": {
            "category_priorities": [clean_text(c, 20) for c in prefs.get("category_priorities") or [] if clean_text(c, 20)],
            "ranking_note": clean_text(prefs.get("ranking_note"), 200),
        },
        "entries": _entries(strategy),
        "updated_at": clean_text(strategy.get("updated_at"), 40),
    }


def _norm(name: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower())
    return " ".join(_NAME_NOISE.sub(" ", text).split())


def match_strategy(hint: str, strategies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Strategies matching a typed name ("Power-Hitting", "power hitting strategy"): exact, then
    starts-with, then contains (punctuation, case and the words strategy/plan/my/the ignored)."""
    want = _norm(hint)
    if not want:
        return [], ""
    named = [(s, _norm(s.get("name"))) for s in strategies]
    for test, how in ((lambda n: n == want, "exact"), (lambda n: n.startswith(want) or want.startswith(n), "prefix"),
                      (lambda n: want in n or n in want, "contains")):
        hits = [s for s, n in named if n and test(n)]
        if hits:
            return hits, how
    return [], ""


def _names(strategies: list[dict[str, Any]]) -> list[str]:
    return [clean_text(s.get("name"), NAME_LIMIT) for s in strategies]


def _pick(session: Mapping[str, Any], strategies: list[dict[str, Any]], name: str, tool_name: str
          ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any], ToolResult | None]:
    """(saved strategy or None, unsaved working copy or None, how it was chosen, failure)."""
    recs = _work_records(session)
    open_id = _open_id(session)
    live_ids = {str(s["id"]) for s in strategies}
    open_rec = recs.get(open_id) if isinstance(recs.get(open_id), dict) else None
    open_new = bool(open_rec and open_rec.get("new") and isinstance(open_rec.get("strategy"), dict))
    how: dict[str, Any] = {"chosen_by": ""}
    if open_id and open_id not in live_ids and not open_new:
        how["open_strategy_missing"] = True  # e.g. deleted elsewhere; never read
    if name:
        hits, _ = match_strategy(name, strategies)
        new_hit = open_new and match_strategy(name, [open_rec["strategy"]])[0]
        if len(hits) == 1:
            chosen, how["chosen_by"] = hits[0], "name"
        elif len(hits) > 1:
            return None, None, how, fail(tool_name, WHICH_STRATEGY,
                                          f"More than one of your strategies matches “{clean_text(name, 60)}”.",
                                          candidates=_names(hits))
        elif new_hit:
            return None, _view(open_rec["strategy"]), {"chosen_by": "name", "never_saved": True}, None
        else:
            return None, None, how, fail(tool_name, UNKNOWN_STRATEGY,
                                          f"You don't have a saved strategy called “{clean_text(name, 60)}”.",
                                          candidates=_names(strategies))
    elif open_id in live_ids:
        chosen, how["chosen_by"] = next(s for s in strategies if str(s["id"]) == open_id), "selected"
    elif open_new:
        return None, _view(open_rec["strategy"]), {"chosen_by": "selected", "never_saved": True}, None
    elif len(strategies) == 1:
        chosen, how["chosen_by"] = strategies[0], "only_one"
    elif not strategies:
        return None, None, how, fail(tool_name, NO_STRATEGIES, "You don't have any saved Draft Strategies yet.")
    else:
        return None, None, how, fail(tool_name, WHICH_STRATEGY, "Which strategy do you mean?",
                                      candidates=_names(strategies))
    rec = recs.get(str(chosen["id"])) if isinstance(recs.get(str(chosen["id"])), dict) else None
    unsaved = None
    if rec and rec.get("dirty") and isinstance(rec.get("strategy"), dict):
        unsaved = _view(rec["strategy"])
    return chosen, unsaved, how, None


def _research(session: Mapping[str, Any], strategy_id: str) -> tuple[list[dict[str, Any]], bool]:
    import draft_strategy_v2 as v2

    try:
        entries = v2.research_log(session, strategy_id)  # type: ignore[arg-type]
    except Exception:
        return [], False
    out = [{"at": clean_text(e.get("at"), 40)[:10], "kind": clean_text(e.get("kind"), 20),
            "text": clean_text(e.get("text"), 1000), "player_key": clean_text(e.get("player_key"), NAME_LIMIT),
            "source": clean_text(e.get("source"), 20)} for e in entries if isinstance(e, dict)]
    return [e for e in out if e["text"]][-RESEARCH_LIMIT:], True


# --- tools -----------------------------------------------------------------------------------


@tool(
    "list_my_strategies", capability=CAPABILITY, needs_session=True, plan_capability=PLAN_CAPABILITY,
    description="The signed-in user's saved Draft Strategies (names, sizes, which one is selected). Read-only.",
    reuses=("draft_strategy_v2.list_strategies_v2",),
)
def list_my_strategies(*, session: Mapping[str, Any]) -> ToolResult:
    strategies, failure = _live(session, "list_my_strategies")
    if failure is not None:
        return failure
    open_id = _open_id(session)
    recs = _work_records(session)
    rows = [{"name": clean_text(s.get("name"), NAME_LIMIT), "players": len(s.get("queue") or []),
             "selected": str(s["id"]) == open_id,
             "unsaved_changes": bool((recs.get(str(s["id"])) or {}).get("dirty")),
             "updated_at": clean_text(s.get("updated_at"), 40)[:10]} for s in strategies]
    open_rec = recs.get(open_id) if isinstance(recs.get(open_id), dict) else None
    never_saved = (clean_text(open_rec["strategy"].get("name"), NAME_LIMIT)
                   if open_rec and open_rec.get("new") and isinstance(open_rec.get("strategy"), dict) else "")
    return ToolResult("list_my_strategies", True, {"strategies": rows, "never_saved_open": never_saved})


@tool(
    "get_my_strategy", capability=CAPABILITY, needs_session=True, plan_capability=PLAN_CAPABILITY,
    description=("One of the user's saved Draft Strategies: its queue (rank, position, pins, the user's notes), "
                 "approach, preferences and research log; the selected strategy unless a name is given. "
                 "Unsaved editor changes are returned separately. Read-only."),
    parameters={"properties": {"name": {"type": "string", "description": "A strategy name as the user typed it."},
                               "player": {"type": "string", "description": "A player the user asked about."}}},
    reuses=("draft_strategy_v2.list_strategies_v2", "draft_strategy_v2.research_log"),
)
def get_my_strategy(*, session: Mapping[str, Any], name: str = "", player: str = "") -> ToolResult:
    strategies, failure = _live(session, "get_my_strategy")
    if failure is not None:
        return failure
    chosen, unsaved, how, failure = _pick(session, strategies, str(name or "").strip(), "get_my_strategy")
    if failure is not None:
        return failure
    data: dict[str, Any] = {**how, "saved": None, "unsaved": unsaved, "research": [], "research_available": True,
                            "strategy_names": _names(strategies)}
    if chosen is not None:
        data["saved"] = _view(chosen)
        data["research"], data["research_available"] = _research(session, str(chosen["id"]))
    # The player isn't in this strategy: where else the user saved them (other live strategies only).
    subject = clean_text(player, NAME_LIMIT)
    view = data["saved"] or data["unsaved"]
    if subject and isinstance(view, dict) and find_entry(subject, view["entries"]) is None:
        elsewhere = []
        for s in strategies:
            if chosen is not None and str(s["id"]) == str(chosen["id"]):
                continue
            other = _view(s)
            hit = find_entry(subject, other["entries"])
            if hit is not None:
                elsewhere.append({"strategy": other["name"], "name": hit["name"], "rank": hit["rank"],
                                  "of": len(other["entries"]), "pinned": hit["pinned"], "note": hit["note"],
                                  "note_source": hit["note_source"]})
        data["elsewhere"] = elsewhere[:ELSEWHERE_LIMIT]
    return ToolResult("get_my_strategy", True, data)


GLOBAL_LIST_KEY = "draft_queue"  # draft_state.DRAFT_QUEUE_KEY (the Global Queue's names, in order)


def _global_names(session: Mapping[str, Any]) -> list[str]:
    raw = session.get(GLOBAL_LIST_KEY)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, (list, tuple)) else []:
        name = str(item or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _global_entries(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    plan = session.get("draft_queue_plan") if isinstance(session.get("draft_queue_plan"), dict) else {}
    own_notes = plan.get("notes") if isinstance(plan.get("notes"), dict) else {}
    pins = {str(p).lower() for p in plan.get("pins") or []}
    out = []
    for rank, raw in enumerate(_global_names(session), start=1):
        name = clean_text(raw, NAME_LIMIT)
        if not name:
            continue
        m = meta.get(name.lower()) if isinstance(meta.get(name.lower()), dict) else {}
        pos = clean_text(m.get("position"), 20)
        out.append({"rank": rank, "name": name, "position": "" if pos == "—" else pos, "pinned": name.lower() in pins,
                    "note": clean_text(own_notes.get(name.lower()), NOTE_LIMIT)})
    return out


def _loaded_from(session: Mapping[str, Any]) -> str:
    """The strategy the Global Queue was loaded from, only while that strategy is still live (read-only)."""
    import draft_strategy_store as store

    loaded = session.get(store.LOADED_KEY)
    if not isinstance(loaded, dict) or not loaded.get("id"):
        return ""
    if _access_error(session, "get_global_list") is not None:
        return ""
    try:
        live = {str(s.get("id")) for s in store.list_strategies(session)}  # type: ignore[arg-type]
    except Exception:
        return ""
    return clean_text(loaded.get("name"), NAME_LIMIT) if str(loaded["id"]) in live else ""


@tool(
    "get_global_list", capability=CAPABILITY, needs_session=True,
    description="The user's Global Queue (free): order, positions, pins and its own notes. Read-only.",
    reuses=("draft_state.DRAFT_QUEUE_KEY (read-only)", "draft_queue_modes.plan (read-only)"),
)
def get_global_list(*, session: Mapping[str, Any]) -> ToolResult:
    return ToolResult("get_global_list", True, {"entries": _global_entries(session),
                                                  "loaded_from": _loaded_from(session)})


@tool(
    "compare_strategy_to_global", capability=CAPABILITY, needs_session=True, plan_capability=PLAN_CAPABILITY,
    description="Players only in a saved strategy, only in the Global Queue, or in both (with both ranks). Read-only.",
    parameters={"properties": {"name": {"type": "string"}}},
    reuses=("draft_strategy_v2.list_strategies_v2", "draft_state.DRAFT_QUEUE_KEY (read-only)"),
)
def compare_strategy_to_global(*, session: Mapping[str, Any], name: str = "") -> ToolResult:
    got = get_my_strategy(session=session, name=name)
    if not got.ok:
        return ToolResult("compare_strategy_to_global", False, got.data, got.error_code, got.message)
    view = got.data["saved"] or got.data["unsaved"]
    if not isinstance(view, dict):
        return fail("compare_strategy_to_global", INTERNAL_ERROR, "I couldn't read that strategy.")
    strat = {e["name"].lower(): e for e in view["entries"]}
    glob = {e["name"].lower(): e for e in _global_entries(session)}
    both = [{"name": strat[k]["name"], "strategy_rank": strat[k]["rank"], "global_rank": glob[k]["rank"]}
            for k in strat if k in glob]
    return ToolResult("compare_strategy_to_global", True, {
        "strategy": view["name"], "from_unsaved": got.data["saved"] is None,
        "never_saved": bool(got.data.get("never_saved")),
        "only_strategy": [strat[k]["name"] for k in strat if k not in glob],
        "only_global": [glob[k]["name"] for k in glob if k not in strat],
        "both": both, "same_order": [e["name"].lower() for e in view["entries"]] == list(glob),
        "strategy_size": len(strat), "global_size": len(glob),
        "unsaved_changes": got.data["unsaved"] is not None and got.data["saved"] is not None,
    })
