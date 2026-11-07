"""Two Draft Queue modes: Fixed (default) and Adaptive (owner request 2026-11-07).

Fixed Queue — "Keep my original order"
    The personal queue (session ``draft_queue``, draft_queue_contract) exactly as the user arranged
    it. Players drafted in the active draft are skipped in this draft only. Nothing reorders it.

Adaptive Queue — "Automatically adjust my draft plan"
    A *separate*, per-draft working order computed from the Fixed queue. It never writes the
    Fixed queue: the user's plan is the baseline, and every user edit (add, remove, drag) changes
    that baseline. Pinned players keep their Fixed position. Auto-pick and every pick still follow
    the Fixed queue and the user's own clicks; the Adaptive order never makes a selection.

How a player's adaptive score is built (deterministic for a given draft state and settings):
    score = W_plan * plan + W_strategy * strategy + W_need * need
    plan      1.0 for the user's #1 available player down to ~0 for the last (their research).
    strategy  where the player ranks among all available players by the selected Draft Strategy
              (draft_strategy_in_draft.rank_pool; Balanced = the Draft Assistant's Decision Score).
    need      category leagues: projected category weaknesses of the user's own roster
              (counting stats summed, rate stats volume-weighted, ERA/WHIP lower-is-better)
              plus open roster slots; points leagues: open roster slots only.
    The plan weight is never below 0.45, so the user's order dominates; a player only passes a
    neighbour when his score is at least ``MOVE_MARGIN`` higher (no reshuffle on tiny changes).

Explanations are built only from that data and from what the user recorded (queue order, pins,
notes, manual moves, a loaded saved strategy). Nothing is said about research that was never
recorded; the panel says so instead.

Privacy: everything here lives in this viewer's session/workspace (MODE_KEY, PLAN_KEY,
ADAPTIVE_KEY are added to the Shared Draft room's private-key list) and is scoped per draft
(draft_queue_contract's draft source), so one mock draft never reorders another draft.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import pandas as pd

MODE_KEY = "draft_queue_mode"            # "fixed" | "adaptive" — personal, saved with the workspace
PLAN_KEY = "draft_queue_plan"            # {"pins": [...], "notes": {lower: text}, "moves": [...]}
ADAPTIVE_KEY = "draft_queue_adaptive"    # {draft_source: per-draft adaptive state}
LOADED_STRATEGY_KEY = "_draft_strategy_loaded"  # set by draft_strategy_store.load_strategy
MODES = ("fixed", "adaptive")
MODE_LABELS = {
    "fixed": "Fixed Queue — keep my original order",
    "adaptive": "Adaptive Queue — adjust my plan as the draft unfolds",
}
MOVE_MARGIN = 0.04       # a player passes a neighbour only when his score is this much higher
MEANINGFUL_MOVE = 2      # rank changes of at least this many places are logged and highlighted
MAX_DRAFTS = 8           # per-draft states kept (oldest dropped)
MAX_HISTORY = 200
MAX_ORDERS = 60
MAX_SUGGESTIONS = 3
_VIEW_CACHE_KEY = "_draft_queue_modes_view_cache"

# (plan, strategy, need) weights per Draft Strategy.
WEIGHTS = {
    "balanced": (0.55, 0.25, 0.20),
    "best_available": (0.50, 0.50, 0.00),
    "value_based": (0.50, 0.40, 0.10),
    "positional_scarcity": (0.50, 0.40, 0.10),
    "roster_aware": (0.45, 0.20, 0.35),
}
_LEVEL_WEIGHT = {"Critical": 1.0, "Low": 0.6, "Moderate": 0.3}
# Pitching categories, used only when the pool carries these projections.
_PITCH_SPECS = (
    ("proj_K", "K", "sum"),
    ("proj_W", "W", "sum"),
    ("proj_SV", "SV", "sum"),
    ("proj_ERA", "ERA", "rate_low"),
    ("proj_WHIP", "WHIP", "rate_low"),
)
_VOLUME_COLS = {"hit": ("proj_AB", "proj_PA"), "pitch": ("proj_IP",)}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _low(name: Any) -> str:
    return str(name or "").strip().lower()


# --- personal settings ---------------------------------------------------------------------


def current_mode(session: Any) -> str:
    mode = str((session.get(MODE_KEY) if hasattr(session, "get") else "") or "fixed")
    return mode if mode in MODES else "fixed"


PERSISTENT_CHOICE_KEYS = (MODE_KEY, "draft_strategy_approach")


def keep_personal_choices(session: Any) -> None:
    """Call at the top of every run, before any widget. Streamlit deletes a widget-bound key at
    the end of a run that doesn't draw the widget (e.g. after navigating to another page), which
    reset the queue mode and strategy to Fixed/Balanced and saved that to the workspace.
    Re-assigning the key detaches it from the old widget instance (Streamlit's documented fix)."""
    for key in PERSISTENT_CHOICE_KEYS:
        try:
            if key in session:
                session[key] = session[key]
        except Exception:
            continue


def plan(session: dict[str, Any]) -> dict[str, Any]:
    p = session.get(PLAN_KEY)
    if not isinstance(p, dict):
        p = {}
    p.setdefault("pins", [])
    p.setdefault("notes", {})
    p.setdefault("moves", [])
    session[PLAN_KEY] = p
    return p


def set_pins(session: dict[str, Any], names: list[str]) -> None:
    plan(session)["pins"] = [str(n).strip() for n in names if str(n).strip()]


def set_note(session: dict[str, Any], name: str, note: str) -> None:
    notes = plan(session)["notes"]
    key, text = _low(name), str(note or "").strip()
    if not key:
        return
    if text:
        notes[key] = text[:500]
    else:
        notes.pop(key, None)


def notes_for(session: dict[str, Any]) -> dict[str, str]:
    """The user's recorded notes: the queue's own notes, then a loaded saved strategy's notes."""
    out: dict[str, str] = {}
    loaded = session.get(LOADED_STRATEGY_KEY)
    if isinstance(loaded, dict):
        for k, v in (loaded.get("notes") or {}).items():
            if str(v or "").strip():
                out[_low(k)] = str(v).strip()
    for k, v in (plan(session).get("notes") or {}).items():
        if str(v or "").strip():
            out[_low(k)] = str(v).strip()
    return out


def note_manual_moves(session: dict[str, Any], before: list[str], after: list[str]) -> None:
    """Record players the user deliberately moved (called by draft_state.sync_draft_queue for a
    reorder of the same players). Only the user's own action is recorded."""
    if not before or not after or before == after or {_low(x) for x in before} != {_low(x) for x in after}:
        return
    old = {_low(n): i for i, n in enumerate(before)}
    moves = plan(session)["moves"]
    for i, name in enumerate(after):
        j = old.get(_low(name))
        if j is not None and j != i and abs(j - i) >= 1:
            # The dragged player moves the most; record every player whose place the user changed.
            moves.append({"player": name, "from": j + 1, "to": i + 1, "at": _now()})
    del moves[:-100]


def moves_for(session: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [m for m in plan(session).get("moves") or [] if _low(m.get("player")) == _low(name)]


# --- the draft ----------------------------------------------------------------------------


def draft_source(session: dict[str, Any]) -> str:
    try:
        from draft_queue_contract import _active_draft_picks

        source, _picks = _active_draft_picks(session)
        return source
    except ImportError:
        return ""


def _room_format(room: dict[str, Any] | None, session: dict[str, Any]) -> str:
    cfg = (room or {}).get("config") if isinstance((room or {}).get("config"), dict) else {}
    return str(cfg.get("fantasy_format") or session.get("room_format") or "5x5 Roto").strip() or "5x5 Roto"


def is_points_league(fmt: str) -> bool:
    return "point" in str(fmt or "").lower()


def _board(room: dict[str, Any] | None) -> list[dict[str, Any]]:
    board = (room or {}).get("draft_board")
    return [e for e in board if isinstance(e, dict)] if isinstance(board, list) else []


def _roster_records(room: dict[str, Any] | None, team: str) -> list[dict[str, Any]]:
    rosters = (room or {}).get("rosters")
    if isinstance(rosters, dict) and isinstance(rosters.get(team), list):
        return [r for r in rosters[team] if isinstance(r, dict)]
    return [e for e in _board(room) if str(e.get("Team") or e.get("Fantasy Team") or "") == team]


def _pool(room: dict[str, Any] | None, session: dict[str, Any]) -> pd.DataFrame:
    """This pick's scored pool when the scoring pass left one, else the room's pool."""
    try:
        import draft_strategy_in_draft as sid

        entry = session.get(sid.SCORED_POOL_KEY)
        if isinstance(entry, dict) and entry.get("pick") == sid._pick_marker(room):
            df = entry.get("df")
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
    except ImportError:
        pass
    pool = (room or {}).get("pool")
    return pool if isinstance(pool, pd.DataFrame) else pd.DataFrame()


def _available(pool: pd.DataFrame, room: dict[str, Any] | None) -> pd.DataFrame:
    if pool.empty or "fullName" not in pool.columns:
        return pool
    taken = {_low(e.get("fullName") or e.get("Player")) for e in _board(room)}
    ids = {str(e.get("playerID") or "") for e in _board(room)} - {""}
    keep = ~pool["fullName"].astype(str).str.strip().str.lower().isin(taken)
    if "playerID" in pool.columns and ids:
        keep &= ~pool["playerID"].astype(str).isin(ids)
    return pool[keep].reset_index(drop=True)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(float("nan"), index=df.index)


# --- team needs ---------------------------------------------------------------------------


def _category_specs(fmt: str, pool: pd.DataFrame) -> list[tuple[str, str, str]]:
    if is_points_league(fmt):
        return []
    try:
        from draft_needs import _hitter_category_specs

        hit = [(c, lbl, "rate" if kind == "rate" else "sum") for c, lbl, kind in _hitter_category_specs(fmt)]
    except ImportError:
        hit = []
    if "proj_BA" not in pool.columns and "proj_AVG" in pool.columns:
        hit = [("proj_AVG" if c == "proj_BA" else c, lbl, kind) for c, lbl, kind in hit]
    pitch = [s for s in _PITCH_SPECS if s[0] in pool.columns]
    if "proj_K" not in pool.columns and "proj_SO" in pool.columns:
        pitch.insert(0, ("proj_SO", "K", "sum"))
    return [s for s in hit if s[0] in pool.columns] + pitch


def _volume(df: pd.DataFrame, col: str) -> pd.Series | None:
    group = "pitch" if col in {"proj_ERA", "proj_WHIP"} else "hit"
    for vol in _VOLUME_COLS[group]:
        if vol in df.columns:
            return _num(df, vol).fillna(0.0)
    return None


def team_needs(room: dict[str, Any] | None, team: str, pool: pd.DataFrame, fmt: str) -> dict[str, Any]:
    """The user's roster: category weaknesses/strengths (category leagues) and open slots."""
    roster = _roster_records(room, team)
    names = {_low(r.get("fullName") or r.get("Player")) for r in roster} - {""}
    full = (room or {}).get("pool") if isinstance((room or {}).get("pool"), pd.DataFrame) else pool
    rows = pd.DataFrame()
    if isinstance(full, pd.DataFrame) and not full.empty and "fullName" in full.columns and names:
        rows = full[full["fullName"].astype(str).str.strip().str.lower().isin(names)]
    if rows.empty and roster:
        rows = pd.DataFrame(roster)
    specs = _category_specs(fmt, full if isinstance(full, pd.DataFrame) else pool)
    # Rostered players whose projections are in this pool (category needs rest on these only).
    projected = 0
    if specs and not rows.empty:
        cols = [c for c, _l, _k in specs if c in rows.columns]
        projected = int(rows[cols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1).sum()) if cols else 0
    weak: list[dict[str, Any]] = []
    strong: list[str] = []
    if specs and not rows.empty and isinstance(full, pd.DataFrame) and not full.empty:
        n = max(len(rows), 1)
        for col, label, kind in specs:
            if col not in rows.columns:
                continue
            league = _num(full, col).dropna()
            mine = _num(rows, col).dropna()
            if league.empty or mine.empty:
                continue
            med = float(league.median())
            if kind == "sum":
                expected, value = med * n, float(mine.sum())
                ratio = value / expected if expected > 0 else 1.0
            else:
                value = float(mine.mean())
                if kind == "rate_low":  # lower is better: a team ERA above the median is the weakness
                    ratio = med / value if value > 0 else 1.0
                else:
                    ratio = value / med if med > 0 else 1.0
                expected = med
            if ratio >= 0.92:
                strong.append(label)
                continue
            level = "Critical" if ratio < 0.70 else ("Low" if ratio < 0.85 else "Moderate")
            weak.append({"label": label, "col": col, "kind": kind, "level": level,
                         "team": round(value, 3), "expected": round(expected, 3)})
    cfg = (room or {}).get("config") if isinstance((room or {}).get("config"), dict) else {}
    slots = cfg.get("slots") if isinstance(cfg.get("slots"), dict) else {}
    counts: dict[str, int] = {}
    for r in roster:
        pos = str(r.get("Primary Position") or r.get("Position") or "").upper()
        if pos:
            counts[pos] = counts.get(pos, 0) + 1
    open_slots = {}
    for pos, n in slots.items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if str(pos).upper() in {"BN", "BENCH", "IL"} or n <= 0:
            continue
        open_slots[str(pos).upper()] = n - counts.get(str(pos).upper(), 0)
    return {"format": fmt, "points": is_points_league(fmt), "weak": weak, "strong": strong,
            "open_slots": open_slots, "roster_size": len(roster), "has_categories": bool(specs),
            "roster_projected": projected,
            "slots_assumed": bool(cfg.get("slots_assumed")), "slots_source": str(cfg.get("slots_source") or ""),
            "slots": {str(p).upper(): n for p, n in slots.items()}}


def _category_impact(available: pd.DataFrame, weak: list[dict[str, Any]], full: pd.DataFrame) -> dict[str, pd.Series]:
    """Per weak category: each available player's percentile (0..1) of what he adds to it.
    Counting stats: the projection itself. Rate stats: (rate - league median) x volume when a
    volume projection exists (a .300 hitter in 600 AB helps AVG more than in 150), else the rate."""
    out: dict[str, pd.Series] = {}
    for w in weak:
        col, kind = w["col"], w["kind"]
        vals = _num(available, col)
        if kind != "sum":
            med = float(_num(full, col).dropna().median()) if col in full.columns else float(vals.median())
            delta = (med - vals) if kind == "rate_low" else (vals - med)
            vol = _volume(available, col)
            vals = delta * vol if vol is not None else delta
        out[w["label"]] = vals.rank(pct=True, method="average").fillna(0.0)
    return out


# --- adaptive order -----------------------------------------------------------------------


def _strategy_rank(available: pd.DataFrame, approach: str, room: dict[str, Any] | None) -> tuple[dict[str, int], dict[str, str]]:
    """(lower-case name -> 1-based rank among available, name -> the strategy's own reason)."""
    if available.empty or "fullName" not in available.columns:
        return {}, {}
    if approach == "balanced":
        col = "Decision Score" if "Decision Score" in available.columns else "Expected Fantasy Value"
        ranked = available.assign(_s=_num(available, col).fillna(-1e18)).sort_values("_s", ascending=False, kind="mergesort")
        reasons: dict[str, str] = {}
    else:
        from draft_strategy_in_draft import rank_pool

        ranked = rank_pool(available, approach, room=room)
        reasons = {}
        if "Strategy Reason" in ranked.columns:
            reasons = {_low(n): str(r) for n, r in zip(ranked["fullName"], ranked["Strategy Reason"]) if str(r)}
    ranks: dict[str, int] = {}
    for i, name in enumerate(ranked["fullName"].astype(str), start=1):
        ranks.setdefault(_low(name), i)
    return ranks, reasons


def score_queue(
    queue: list[str], available: pd.DataFrame, approach: str, needs: dict[str, Any],
    room: dict[str, Any] | None, full: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Per queued available player: score components and the facts behind them. Pure."""
    w_plan, w_strat, w_need = WEIGHTS.get(approach, WEIGHTS["balanced"])
    n = max(len(queue), 1)
    ranks, reasons = _strategy_rank(available, approach, room)
    total = max(len(ranks), 1)
    by_name: dict[str, pd.Series] = {}
    if not available.empty and "fullName" in available.columns:
        for idx, name in zip(available.index, available["fullName"].astype(str)):
            by_name.setdefault(_low(name), available.loc[idx])
    impact = _category_impact(available, needs.get("weak") or [], full) if needs.get("weak") else {}
    out: dict[str, dict[str, Any]] = {}
    for i, name in enumerate(queue):
        key = _low(name)
        row = by_name.get(key)
        plan_s = 1.0 - i / n
        rank = ranks.get(key)
        strat_s = 1.0 - (rank - 1) / total if rank else 0.5
        pos = str(row.get("Primary Position") or "").upper() if row is not None else ""
        open_n = (needs.get("open_slots") or {}).get(pos)
        pos_s = 0.5 if open_n is None else (1.0 if open_n > 0 else 0.0)
        cat_hits = []
        cat_s = None
        if impact and row is not None:
            num = den = 0.0
            for w in needs["weak"]:
                pct = float(impact[w["label"]].get(row.name, 0.0))
                weight = _LEVEL_WEIGHT.get(w["level"], 0.3)
                num += weight * pct
                den += weight
                if pct >= 0.7:
                    proj = row.get(w["col"])
                    cat_hits.append({"label": w["label"], "level": w["level"], "pct": pct,
                                     "projection": None if pd.isna(proj) else float(proj), "kind": w["kind"]})
            cat_s = num / den if den else None
        need_s = pos_s if cat_s is None else 0.6 * cat_s + 0.4 * pos_s
        if row is None:
            strat_s = need_s = 0.5  # no projection found: neutral, the user's order decides
        out[key] = {
            "name": name, "plan_rank": i + 1, "found": row is not None, "position": pos,
            "strategy_rank": rank, "strategy_total": total, "strategy_reason": reasons.get(key, ""),
            "open_slots_at_position": open_n, "categories": cat_hits,
            "plan": plan_s, "strategy": strat_s, "need": need_s,
            "score": w_plan * plan_s + w_strat * strat_s + w_need * need_s,
        }
    return out


def adaptive_order(fixed_available: list[str], scores: dict[str, dict[str, Any]], pins: list[str],
                   previous: list[str] | None = None) -> list[str]:
    """Order the available queued players by score, starting from ``previous`` (else the Fixed
    order); a player passes a neighbour only by ``MOVE_MARGIN``; pinned players keep their Fixed
    position. Deterministic."""
    pinned = {_low(p) for p in pins}
    fixed_pos = {_low(n): i for i, n in enumerate(fixed_available)}
    start = [n for n in (previous or []) if _low(n) in fixed_pos and _low(n) not in pinned]
    seen = {_low(n) for n in start}
    for n in fixed_available:  # newly queued players enter at their Fixed place
        if _low(n) not in seen and _low(n) not in pinned:
            start.insert(min(fixed_pos[_low(n)], len(start)), n)
            seen.add(_low(n))
    score = lambda n: float((scores.get(_low(n)) or {}).get("score", 0.0))  # noqa: E731
    result: list[str] = []
    for name in start:  # insertion with hysteresis
        result.append(name)
        j = len(result) - 1
        while j > 0 and score(result[j]) > score(result[j - 1]) + MOVE_MARGIN:
            result[j - 1], result[j] = result[j], result[j - 1]
            j -= 1
    for name in fixed_available:
        if _low(name) in pinned:
            result.insert(min(fixed_pos[_low(name)], len(result)), name)
    return result


# --- explanations (facts only) ------------------------------------------------------------


def _ordinal_pct(pct: float) -> str:
    top = max(1, int(round((1.0 - pct) * 100)))
    return f"top {top}%" if top <= 50 else "above the median"


def _fmt_proj(value: float | None, kind: str) -> str:
    if value is None:
        return ""
    if kind != "sum":
        return f"{value:.3f}".lstrip("0") if value < 1 else f"{value:.2f}"
    return f"{value:.0f}"


def explain_move(
    name: str, from_rank: int, to_rank: int, fixed_rank: int | None, facts: dict[str, Any],
    approach: str, needs: dict[str, Any], snapshot: dict[str, Any], session: dict[str, Any],
    passed: list[str],
) -> dict[str, Any]:
    from draft_strategy_in_draft import LABELS

    up = to_rank < from_rank
    reasons: list[str] = []
    if facts.get("categories") and up:
        weak_txt = " and ".join(f"{c['label']}" for c in facts["categories"][:2])
        level = facts["categories"][0]["level"].lower()
        proj = ", ".join(
            f"{_fmt_proj(c['projection'], c['kind'])} {c['label']} ({_ordinal_pct(c['pct'])} of available)"
            for c in facts["categories"][:2] if c.get("projection") is not None
        )
        reasons.append(f"Your projected team is {level} in {weak_txt}" + (f"; he projects {proj}." if proj else "."))
    open_n = facts.get("open_slots_at_position")
    if open_n is not None and facts.get("position"):
        if up and open_n > 0:
            reasons.append(f"You still have {open_n} open {facts['position']} slot{'s' if open_n != 1 else ''}.")
        elif not up and open_n <= 0:
            reasons.append(f"Your {facts['position']} slots are already filled.")
    if facts.get("strategy_rank"):
        label = LABELS.get(approach, approach)
        line = f"{label}: #{facts['strategy_rank']} of {facts['strategy_total']} available players"
        if facts.get("strategy_reason"):
            line += f" ({facts['strategy_reason']})"
        reasons.append(line + ".")
    if not facts.get("found"):
        reasons.append("No projection was found for him in this draft's pool, so only your order applies.")
    if up and passed:
        reasons.append("Moves ahead of " + ", ".join(passed[:3]) + (" (and others)" if len(passed) > 3 else "")
                       + ", whom you ranked higher.")
    note = notes_for(session).get(_low(name))
    if note:
        reasons.append(f"Your note: “{note}”.")
    for m in moves_for(session, name)[-1:]:
        verb = "up" if m["to"] < m["from"] else "down"
        reasons.append(f"You moved him {verb} yourself (#{m['from']} → #{m['to']}).")
    saved = snapshot.get("saved_strategy") if isinstance(snapshot.get("saved_strategy"), dict) else None
    if saved and saved.get("approach") == approach:
        alignment = f"Consistent with your saved strategy “{saved.get('name')}” ({LABELS.get(approach, approach)})."
        follows = True
    elif saved:
        alignment = (f"Uses {LABELS.get(approach, approach)}, which differs from your saved strategy "
                     f"“{saved.get('name')}” ({LABELS.get(saved.get('approach'), saved.get('approach'))}).")
        follows = False
    else:
        alignment = f"No saved strategy was recorded; this follows the {LABELS.get(approach, approach)} strategy you selected."
        follows = True
    headline = f"{name} moved {'up' if up else 'down'} from #{from_rank} to #{to_rank}"
    if fixed_rank:
        headline += f" (#{fixed_rank} in your Fixed queue)"
    return {"player": name, "from": from_rank, "to": to_rank, "fixed_rank": fixed_rank,
            "direction": "up" if up else "down", "headline": headline + ".",
            "reasons": reasons, "alignment": alignment, "follows_strategy": follows,
            "data": {k: facts.get(k) for k in ("plan", "strategy", "need", "score", "strategy_rank",
                                                "categories", "open_slots_at_position", "position")}}


# --- per-draft state ----------------------------------------------------------------------


def _states(session: dict[str, Any]) -> dict[str, Any]:
    states = session.get(ADAPTIVE_KEY)
    if not isinstance(states, dict):
        states = {}
        session[ADAPTIVE_KEY] = states
    return states


def _snapshot(session: dict[str, Any], queue: list[str], room: dict[str, Any] | None, approach: str) -> dict[str, Any]:
    loaded = session.get(LOADED_STRATEGY_KEY)
    try:
        from draft_strategy_store import current_draft_context

        ctx = current_draft_context(session)
    except Exception:
        ctx = {}
    cfg = (room or {}).get("config") if isinstance((room or {}).get("config"), dict) else {}
    ctx["room"] = {k: copy.deepcopy(cfg.get(k)) for k in ("fantasy_format", "num_teams", "rounds", "slots", "league_name")
                   if cfg.get(k) not in (None, "")}
    return {
        "players": list(queue),
        "taken_at": _now(),
        "approach": approach,
        "saved_strategy": ({k: loaded.get(k) for k in ("id", "name", "approach")} if isinstance(loaded, dict) else None),
        "pins": list(plan(session)["pins"]),
        "notes": dict(notes_for(session)),
        "moves": copy.deepcopy(plan(session)["moves"][-50:]),
        "context": ctx,
    }


def draft_state(session: dict[str, Any], source: str) -> dict[str, Any] | None:
    st = _states(session).get(source)
    return st if isinstance(st, dict) else None


def _board_fingerprint(room: dict[str, Any] | None) -> list[list[Any]]:
    return [[int(e.get("Pick") or i + 1), _low(e.get("fullName") or e.get("Player")),
             str(e.get("Team") or e.get("Fantasy Team") or "")] for i, e in enumerate(_board(room))]


def refresh(session: dict[str, Any], room: dict[str, Any] | None, team: str, *, source: str | None = None) -> dict[str, Any]:
    """Bring this draft's adaptive state up to date and return a view of it. Safe every rerun:
    nothing is recomputed unless the picks, the queue, the strategy or the pins changed. Never
    writes the Fixed queue or the room.

    ``source`` names the draft explicitly (the Draft Room Simulator passes its own board even
    while a Live Draft is the active draft); availability then comes from ``room``'s board."""
    from draft_queue_contract import split_queue_for_active_draft
    from draft_strategy_in_draft import current_approach

    if source is None:
        source = draft_source(session)
        fixed_available, drafted_here = split_queue_for_active_draft(session)
    else:
        from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list

        taken = {_low(e.get("fullName") or e.get("Player")) for e in _board(room)}
        queue = _normalize_player_list(session.get(DRAFT_QUEUE_KEY))
        fixed_available = [q for q in queue if _low(q) not in taken]
        drafted_here = [q for q in queue if _low(q) in taken]
    approach = current_approach(session)
    mode = current_mode(session)
    view = {"source": source, "mode": mode, "approach": approach, "fixed": fixed_available,
            "drafted_here": drafted_here, "adaptive": list(fixed_available), "history": [], "suggestions": [],
            "needs": {}, "snapshot": None, "facts": {}}
    if not source:
        return view
    states = _states(session)
    state = states.get(source)
    picks = len(_board(room))
    if not isinstance(state, dict):
        from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list

        state = {"snapshot": _snapshot(session, _normalize_player_list(session.get(DRAFT_QUEUE_KEY)), room, approach),
                 "orders": {}, "history": [], "picks_seen": picks, "reviewed_at": 0, "sig": None}
        states[source] = state
        for stale in list(states)[:-MAX_DRAFTS]:
            states.pop(stale, None)
    view["snapshot"] = state["snapshot"]
    pins = [p for p in plan(session)["pins"] if _low(p) in {_low(x) for x in fixed_available}]
    # JSON-friendly (the state is saved with the workspace), so a restored state still matches.
    sig = [picks, [_low(x) for x in fixed_available], approach, sorted(_low(p) for p in pins), str(team or ""), mode]
    board = _board_fingerprint(room)
    old_board = state.get("board") if isinstance(state.get("board"), list) else None
    if old_board is not None:
        # Undo, removal or a changed earlier selection: forget everything after the first pick
        # that differs, then recalculate from the order as it stood before it.
        same = 0
        while same < min(len(old_board), len(board)) and list(old_board[same]) == list(board[same]):
            same += 1
        if same < len(old_board):
            state["history"] = [h for h in state["history"] if int(h.get("pick") or 0) <= same]
            state["orders"] = {k: v for k, v in state["orders"].items() if int(k) <= same}
            state["reviewed_at"] = min(int(state.get("reviewed_at") or 0), same)
            state["picks_seen"] = same
            state["sig"] = None
    state["board"] = board
    pool = _pool(room, session)
    fmt = _room_format(room, session)
    cache_key = repr([source, sig, board, fmt, id(pool), len(pool), mode])
    cached = session.get(_VIEW_CACHE_KEY)
    if (isinstance(cached, dict) and cached.get("key") == cache_key and state.get("sig") == sig
            and str(picks) in state["orders"]):
        out = dict(cached["view"])
        out.update({"history": list(state["history"]), "reviewed_at": int(state.get("reviewed_at") or 0),
                    "snapshot": state["snapshot"]})
        return out
    available = _available(pool, room)
    full = (room or {}).get("pool") if isinstance((room or {}).get("pool"), pd.DataFrame) else pool
    needs = team_needs(room, team, available, fmt)
    view["needs"] = needs
    scores = score_queue(fixed_available, available, approach, needs, room, full)
    view["facts"] = scores
    if state.get("sig") == sig and str(picks) in state["orders"]:
        order = [n for n in state["orders"][str(picks)] if _low(n) in {_low(x) for x in fixed_available}]
    else:
        prev_keys = sorted((int(k) for k in state["orders"]), reverse=True)
        previous = state["orders"][str(prev_keys[0])] if prev_keys else list(fixed_available)
        order = adaptive_order(fixed_available, scores, pins, previous)
        # Switching Fixed -> Adaptive: explain every difference from the Fixed order once.
        was_fixed = state.get("last_mode") != "adaptive"
        explain_from = list(fixed_available) if (mode == "adaptive" and was_fixed) else previous
        prev_live = [n for n in explain_from if _low(n) in {_low(x) for x in fixed_available}]
        prev_rank = {_low(n): i + 1 for i, n in enumerate(prev_live)}
        fixed_rank = {_low(n): i + 1 for i, n in enumerate(fixed_available)}
        trigger = "pick" if picks > int(state.get("picks_seen") or 0) else (
            "strategy" if state.get("sig") and state["sig"][2] != approach else "update")
        # The audit history records only what Adaptive mode did; Fixed mode just previews it.
        for i, name in enumerate(order if mode == "adaptive" else [], start=1):
            before = prev_rank.get(_low(name))
            if before is None or abs(before - i) < MEANINGFUL_MOVE:
                continue
            below_now = {_low(x) for x in order[i:]}
            # Players the user ranked above him whom he is now ahead of.
            passed = [n for n in fixed_available[: fixed_rank[_low(name)] - 1] if _low(n) in below_now]
            event = explain_move(name, before, i, fixed_rank.get(_low(name)), scores.get(_low(name)) or {},
                                 approach, needs, state["snapshot"], session, passed if i < before else [])
            event.update({"pick": picks, "trigger": trigger, "at": _now()})
            state["history"].append(event)
        del state["history"][:-MAX_HISTORY]
        state["orders"][str(picks)] = list(order)
        for k in sorted(state["orders"], key=int)[:-MAX_ORDERS]:
            state["orders"].pop(k, None)
        state["sig"] = sig
        state["last_mode"] = mode
        state["picks_seen"] = picks
    view["adaptive"] = order
    view["history"] = list(state["history"])
    view["reviewed_at"] = int(state.get("reviewed_at") or 0)
    view["suggestions"] = suggestions(fixed_available, drafted_here, available, approach, needs, room, full)
    session[_VIEW_CACHE_KEY] = {"key": cache_key, "view": view}  # this run only; never saved
    return view


def mark_reviewed(session: dict[str, Any]) -> None:
    state = draft_state(session, draft_source(session))
    if state is not None:
        state["reviewed_at"] = int(state.get("picks_seen") or 0)


def comparison_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Side by side: Fixed rank, Adaptive rank, movement, latest reason (meaningful moves only)."""
    fixed = view.get("fixed") or []
    adaptive = view.get("adaptive") or []
    fixed_rank = {_low(n): i + 1 for i, n in enumerate(fixed)}
    latest: dict[str, dict[str, Any]] = {}
    for h in view.get("history") or []:
        latest[_low(h.get("player"))] = h
    rows = []
    for i in range(max(len(fixed), len(adaptive))):
        a = adaptive[i] if i < len(adaptive) else ""
        delta = (fixed_rank.get(_low(a), i + 1) - (i + 1)) if a else 0
        rows.append({
            "Fixed Queue": f"#{i + 1} {fixed[i]}" if i < len(fixed) else "",
            "Adaptive Queue": (f"#{i + 1} {a}" + (" ↑" if delta >= MEANINGFUL_MOVE else (" ↓" if delta <= -MEANINGFUL_MOVE else ""))) if a else "",
            "Move": (f"+{delta}" if delta > 0 else str(delta)) if abs(delta) >= MEANINGFUL_MOVE else "",
            "Why": (latest.get(_low(a)) or {}).get("reasons", [""])[0] if abs(delta) >= MEANINGFUL_MOVE else "",
        })
    return rows


def significant_changes(view: dict[str, Any], *, since_pick: int = 0, limit: int = 5) -> list[dict[str, Any]]:
    """The biggest net movements since a pick (one entry per player, latest event)."""
    latest: dict[str, dict[str, Any]] = {}
    for h in view.get("history") or []:
        if int(h.get("pick") or 0) > since_pick or (since_pick == 0):
            latest[_low(h.get("player"))] = h
    fixed_rank = {_low(n): i + 1 for i, n in enumerate(view.get("fixed") or [])}
    now_rank = {_low(n): i + 1 for i, n in enumerate(view.get("adaptive") or [])}
    out = []
    for key, h in latest.items():
        if key not in now_rank:
            continue
        net = fixed_rank.get(key, now_rank[key]) - now_rank[key]
        if abs(net) >= MEANINGFUL_MOVE:
            out.append({**h, "net": net, "now": now_rank[key]})
    return sorted(out, key=lambda h: (-abs(h["net"]), h["now"]))[:limit]


def suggestions(fixed_available: list[str], drafted_here: list[str], available: pd.DataFrame, approach: str,
                needs: dict[str, Any], room: dict[str, Any] | None, full: pd.DataFrame) -> list[dict[str, Any]]:
    """Up to three strong available players outside the queue, with the facts why. Never added
    automatically: the user decides."""
    if available.empty or "fullName" not in available.columns:
        return []
    ranks, reasons = _strategy_rank(available, approach, room)
    queued = {_low(n) for n in fixed_available + drafted_here}
    best_queued = min((ranks[_low(n)] for n in fixed_available if _low(n) in ranks), default=None)
    impact = _category_impact(available, needs.get("weak") or [], full) if needs.get("weak") else {}
    by_name = {_low(n): available.loc[i] for i, n in zip(available.index, available["fullName"].astype(str))}
    out = []
    for name_l, rank in sorted(ranks.items(), key=lambda kv: kv[1])[:10]:
        if name_l in queued:
            continue
        row = by_name[name_l]
        why = []
        if best_queued is None or rank < best_queued:
            why.append(f"#{rank} of {len(ranks)} available by your strategy"
                       + (f", ahead of every player left in your queue" if best_queued else "")
                       + (f" ({reasons[name_l]})" if reasons.get(name_l) else "") + ".")
        for w in needs.get("weak") or []:
            pct = float(impact[w["label"]].get(row.name, 0.0)) if impact else 0.0
            if w["level"] == "Critical" and pct >= 0.8:
                why.append(f"Helps your critical {w['label']} need ({_ordinal_pct(pct)} of available).")
        if why:
            out.append({"player": str(row["fullName"]), "position": str(row.get("Primary Position") or ""),
                        "strategy_rank": rank, "reasons": why})
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


def restore_snapshot_to_queue(session: dict[str, Any], *, confirmed: bool) -> list[str]:
    """Put this draft's saved original plan back as the Fixed queue (explicit and confirmed)."""
    if not confirmed:
        raise ValueError("Confirm before replacing your queue with the saved original plan.")
    state = draft_state(session, draft_source(session))
    players = list(((state or {}).get("snapshot") or {}).get("players") or [])
    if players:
        from draft_state import sync_draft_queue

        sync_draft_queue(session, players, reason="queue_restore_original_plan")
    return players


def research_limitations(session: dict[str, Any], snapshot: dict[str, Any] | None) -> list[str]:
    """What the explanations cannot draw on, said plainly."""
    out = []
    snap = snapshot or {}
    if not snap.get("saved_strategy"):
        out.append("No saved strategy was loaded for this queue, so Adaptive starts from your queue order "
                   "and the strategy selected here.")
    if not notes_for(session) and not snap.get("notes"):
        out.append("No research notes were recorded, so explanations use only projections, your roster and your order.")
    if not plan(session).get("moves") and not snap.get("moves"):
        out.append("No manual reorders were recorded for this queue.")
    return out


# --- Draft Room Simulator -----------------------------------------------------------------


def simulator_source(session: dict[str, Any]) -> str:
    """The simulator board's draft identity (the same one draft_queue_contract uses)."""
    return f"sim:{int(session.get('_simulator_board_epoch') or 0)}"


def simulator_room(session: dict[str, Any], pool: pd.DataFrame | None, *, teams: list[str], your_team: str,
                   fmt: str) -> dict[str, Any]:
    """The simulator board in the shape the engine reads (read-only view; the board is unchanged).

    Each filled pick becomes a board entry with that player's projections from the simulator's own
    scored pool, so a player the user assigns to an opposing team is unavailable in this mock only.
    The simulator has no roster-slot settings, so starter slots are assumed (marked as such)."""
    from draft_room_state import DRAFT_ROOM_TABLE_KEY, _player_cell_filled, coerce_board_table
    from draft_strategy_in_draft import _DEFAULT_STARTERS

    pool = pool if isinstance(pool, pd.DataFrame) else pd.DataFrame()
    by_name: dict[str, dict[str, Any]] = {}
    if not pool.empty and "fullName" in pool.columns:
        for rec in pool.to_dict("records"):
            by_name.setdefault(_low(rec.get("fullName")), rec)
    df = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    entries: list[dict[str, Any]] = []
    rosters: dict[str, list[dict[str, Any]]] = {str(t): [] for t in teams}
    if not df.empty and "Player" in df.columns:
        work = df.sort_values("Pick", kind="stable") if "Pick" in df.columns else df
        for i, row in enumerate(work.to_dict("records")):
            if not _player_cell_filled(row.get("Player")):
                continue
            name = str(row.get("Player")).strip()
            rec = dict(by_name.get(_low(name)) or {"fullName": name})
            rec.update({"fullName": name, "Pick": int(row.get("Pick") or i + 1), "Team": str(row.get("Team") or "")})
            entries.append(rec)
            rosters.setdefault(rec["Team"], []).append(rec)
    positions = set(pool["Primary Position"].astype(str).str.upper()) if "Primary Position" in pool.columns else set()
    slots, slots_source = simulator_roster_slots(session)
    if not slots:
        slots = {p: n for p, n in _DEFAULT_STARTERS.items() if not positions or p in positions}
        slots_source = ""
    return {"draft_room_id": simulator_source(session), "teams": list(teams), "draft_board": entries,
            "rosters": rosters, "pool": pool,
            "config": {"fantasy_format": fmt, "num_teams": len(teams), "your_team": your_team, "slots": slots,
                       "slots_assumed": not slots_source, "slots_source": slots_source}}


def simulator_roster_slots(session: dict[str, Any]) -> tuple[dict[str, int], str]:
    """Roster slots for the simulator from real league settings, with where they came from:
    the active league's roster settings, else the draft settings shared with the draft tools.
    ({}, "") when neither has slots; the caller then assumes standard starters and says so."""
    candidates: list[tuple[Any, str]] = []
    try:
        from fantasy_league_context import get_active_league_context, resolve_context_draft_slot_config

        ctx = get_active_league_context(session)
        name = str((ctx or {}).get("league_name") or (ctx or {}).get("name") or "").strip()
        candidates.append((resolve_context_draft_slot_config(ctx).get("slots"),
                           f"your active league{(' ' + name) if name else ''}'s roster settings"))
    except Exception:
        pass
    shared = session.get("draft_shared_settings")
    if isinstance(shared, dict):
        candidates.append((shared.get("slots") or shared.get("roster_slots"), "your draft settings"))
    for raw, label in candidates:
        if not isinstance(raw, dict):
            continue
        slots: dict[str, int] = {}
        for pos, n in raw.items():
            try:
                if int(n) > 0:
                    slots[str(pos).upper()] = int(n)
            except (TypeError, ValueError):
                continue
        if any(p not in {"BN", "BENCH", "IL"} for p in slots):
            return slots, label
    return {}, ""
