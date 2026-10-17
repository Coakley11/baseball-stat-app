"""Plain-language answers for the U4 draft pages. Pure functions, no Streamlit.

Same rules as ``u1_answers`` / ``u2_answers`` / ``u3_answers``: every sentence comes from values
the page already computed. Draft progress comes from ``draft_room_state`` (the canonical board
summary), recommendations from the Draft Assistant's own ranked pool (Decision Score order, no
re-scoring here), Draft Lab results from its own analysis tables, and the library from the saved
draft archives.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from u2_answers import _join, _num, _plural

# canonical draft meta "source" → where the board's last change came from
_BOARD_SOURCES = (
    (("validated_import",), "an imported draft file"),
    (("live_draft_room", "completed_live_draft_import"), "the Live Draft Room"),
    (("draft_player:", "draft_room_simulator", "board_pick_assign", "undo_last_pick"), "picks entered here"),
)


def board_source_text(source: str) -> str:
    s = str(source or "").strip()
    for prefixes, text in _BOARD_SOURCES:
        if any(s == p or (p.endswith(":") and s.startswith(p)) for p in prefixes):
            return text
    return ""


def _pick_text(n: Any) -> str:
    v = _num(n)
    return f"#{int(v)}" if v is not None else "—"


def draft_room_answer(summary: Mapping[str, Any], *, your_team: str = "", rounds: int = 0,
                      source: str = "", unsaved: bool = False, on_clock_team: str = "") -> dict[str, Any]:
    """Draft Room Simulator: where the board stands. ``summary`` is
    ``draft_room_state.draft_board_summary_for_team`` for the board on screen."""
    filled = int(_num(summary.get("filled_picks")) or 0)
    total = int(_num(summary.get("total_picks")) or 0)
    teams = int(_num(summary.get("num_teams")) or 0)
    cur, rnd = summary.get("current_pick"), summary.get("current_round")
    complete = bool(summary.get("draft_complete"))
    rounds = int(rounds or summary.get("total_rounds") or 0)
    shape = f"{teams} teams × {rounds} rounds" if teams and rounds else f"{total} picks"
    if complete:
        headline = f"Draft complete: all {total} picks made"
    elif filled == 0:
        headline = f"Ready to draft: {shape}, no picks yet"
    else:
        headline = f"Pick {int(_num(cur) or filled + 1)} is next (round {int(_num(rnd) or 1)}): {filled} of {total} picks made"
    parts = []
    if not complete and on_clock_team:
        parts.append(f"{on_clock_team} is on the clock.")
    nxt = summary.get("your_next_pick")
    if your_team and not complete:
        parts.append(f"{your_team} picks next at {_pick_text(nxt)}." if _num(nxt) is not None
                     else f"{your_team} has no open picks left.")
    src = board_source_text(source)
    if src and filled:
        parts.append(f"Last change came from {src}.")
    # The local-edit flag also follows settings syncs, so it only means something once picks exist.
    unsaved = bool(unsaved and filled)
    if filled:
        parts.append("You have unsaved changes: press Save Draft to keep them through a refresh." if unsaved
                     else "No unsaved changes.")
    tiles = [
        ("Picks", f"{filled}/{total}", shape if teams and rounds else ""),
        ("On the clock", "Done" if complete else _pick_text(cur), "" if complete else f"round {int(_num(rnd) or 1)}"),
        ("Your next pick", "—" if complete else _pick_text(nxt), your_team),
        ("Board", "Unsaved" if unsaved else ("Saved" if filled else "Empty"), ""),
    ]
    return {"headline": headline, "body": " ".join(parts), "tiles": tiles,
            "tone": "warn" if unsaved else ("good" if complete else ""), "complete": complete}


def _decision_score(row: Mapping[str, Any]) -> float | None:
    for col in ("Decision Score", "Pick Score"):
        v = _num(row.get(col))
        if v is not None:
            return v
    return None


def draft_assistant_answer(best: Mapping[str, Any] | None, *, best_value: Mapping[str, Any] | None = None,
                           summary: Mapping[str, Any] | None = None, gaps: Sequence[Any] = (),
                           team: str = "") -> dict[str, Any]:
    """Draft Assistant: the recommendation it already ranked first ("Best pick for your team
    now", Decision Score order), with its own "Why this pick", plus pick timing and the roster's
    open positions (``gaps``: positions still needed, not ranked)."""
    summary = summary or {}
    needs = list(dict.fromkeys(str(g).strip() for g in (gaps or []) if str(g).strip()))
    cur, nxt = summary.get("current_pick"), summary.get("your_next_pick")
    complete = bool(summary.get("draft_complete"))
    tiles = [
        ("Your next pick", "—" if complete else _pick_text(nxt), team),
        ("On the clock", "Done" if complete else _pick_text(cur), ""),
        ("Roster needs", str(len(needs)), ", ".join(needs[:3]) + ("…" if len(needs) > 3 else "")),
    ]
    if complete:
        return {"headline": "Your draft is complete", "body": "Review your roster in Draft Room Simulator or Draft Lab.",
                "tiles": tiles, "tone": "good", "player": "", "compare": []}
    if not best:
        return {"headline": "No recommendation yet",
                "body": "Rankings need your draft settings and an available player pool. Check the settings below.",
                "tiles": tiles, "tone": "warn", "player": "", "compare": []}
    name = str(best.get("fullName") or best.get("Player") or "").strip()
    pos = str(best.get("Primary Position") or "").strip()
    headline = f"Best pick now: {name}" + (f" ({pos})" if pos else "")
    parts = []
    why = str(best.get("Why this pick") or "").strip()
    if why:
        parts.append(why.rstrip(".") + ".")
    compare = []
    if best_value:
        bv_name = str(best_value.get("fullName") or best_value.get("Player") or "").strip()
        if bv_name and bv_name != name:
            parts.append(f"Highest raw value is {bv_name}, before roster fit.")
            compare = [name, bv_name]
    if needs:
        parts.append(f"Your roster still needs {_join(needs[:4])}.")
    score = _decision_score(best)
    if score is not None:
        tiles.insert(0, ("Decision Score", f"{score:.2f}", name.split()[-1] if name else ""))
    return {"headline": headline, "body": " ".join(parts), "tiles": tiles, "tone": "", "player": name, "compare": compare}


def _score_col(df: pd.DataFrame) -> str:
    # "Total Projected Fantasy Value" is shown as "Draft Lab Team Score" (draft_score_display).
    for col in ("Draft Lab Team Score", "Total Projected Fantasy Value"):
        if col in df.columns:
            return col
    return ""


def draft_lab_answer(team_summary: pd.DataFrame | None, pick_analysis: pd.DataFrame | None = None, *,
                     team_col: str = "Fantasy Team", rank_col: str = "Projected Team Rank",
                     total_picks: int = 0) -> dict[str, Any] | None:
    """Draft Lab: the projected best draft from the simulation's own team ranking, its margin,
    that team's "Best Pick" (with the analysis' own reason) and its open position gaps."""
    if team_summary is None or team_summary.empty or team_col not in team_summary.columns:
        return None
    ranked = team_summary.copy()
    if rank_col in ranked.columns:
        ranked = ranked.assign(_r=pd.to_numeric(ranked[rank_col], errors="coerce")).sort_values("_r", kind="stable")
    winner = ranked.iloc[0]
    team = str(winner[team_col])
    col = _score_col(ranked)
    score = _num(winner.get(col)) if col else None
    parts = []
    if score is not None and len(ranked) > 1:
        second = ranked.iloc[1]
        s2 = _num(second.get(col))
        if s2 is not None:
            parts.append(f"Draft Lab Team Score {score:,.2f}, {score - s2:,.2f} ahead of {second[team_col]}.")
    best_pick = ""
    if pick_analysis is not None and not pick_analysis.empty and {"Pick Type", "Player", team_col} <= set(pick_analysis.columns):
        rows = pick_analysis[(pick_analysis["Pick Type"] == "Best Pick") & (pick_analysis[team_col].astype(str) == team)]
        if not rows.empty:
            best_pick = str(rows.iloc[0]["Player"])
            reason = str(rows.iloc[0].get("Reason") or "").strip()
            parts.append(f"Best pick: {best_pick}" + (f" ({reason.rstrip('.')})." if reason else "."))
    gaps = str(winner.get("Position Gaps") or "").strip()
    if gaps and gaps != "None":
        parts.append(f"Still open on that roster: {gaps}.")
    elif gaps == "None":
        parts.append("That roster filled every required position.")
    teams_n = len(ranked)
    tiles = [("Best draft", team, ""), ("Team score", f"{score:,.2f}" if score is not None else "—", "Draft Lab Team Score"),
             ("Teams", str(teams_n), ""), ("Picks", f"{int(total_picks):,}" if total_picks else "—", "")]
    return {"headline": f"Projected best draft: {team}", "body": " ".join(parts), "tiles": tiles,
            "team": team, "best_pick": best_pick}


def library_answer(archives: Sequence[Mapping[str, Any]], *, active: Mapping[str, Any] | None = None,
                   active_team: str = "", active_team_count: int = 0) -> dict[str, Any]:
    """Saved Draft Library: the active league, how many saved drafts there are and the most
    recent one (``archives`` is newest first, as ``list_draft_archives`` returns them)."""
    n = len(archives)
    recent = archives[0] if archives else None
    recent_name = str((recent or {}).get("draft_name") or "Saved draft").strip()
    recent_when = str((recent or {}).get("updated_at") or (recent or {}).get("created_at") or "")[:10]
    active_id = str((active or {}).get("draft_id") or "")
    if active:
        title = str(active.get("draft_name") or "Saved draft").strip()
        headline = f"Active league: {title}"
        bits = []
        if active_team:
            bits.append(f"Your team: {active_team}")
        if active_team_count:
            bits.append(_plural(active_team_count, "team"))
        body = (" · ".join(bits) + ". " if bits else "") + "League Standings, Lineup & Trades and Waiver Wire use this league."
    elif n:
        headline = "No active league yet"
        body = "Pick a saved draft and Set Active, so League Standings, Lineup & Trades and Waiver Wire know which league to use."
    else:
        headline = "No saved drafts yet"
        body = "Finish a draft in Live Draft Room or Draft Room Simulator and save it, and it appears here."
    if n:
        body += f" {_plural(n, 'saved draft')}; most recent: {recent_name}" + (f" ({recent_when})." if recent_when else ".")
    recent_is_active = bool(recent and str(recent.get("draft_id") or "") == active_id)
    tiles = [("Active league", str((active or {}).get("draft_name") or "None"), active_team),
             ("Saved drafts", str(n), ""),
             ("Most recent", recent_name if recent else "—", recent_when + (" · active" if recent_is_active else ""))]
    return {"headline": headline, "body": body, "tiles": tiles, "tone": "" if active else "warn",
            "recent_id": str((recent or {}).get("draft_id") or ""), "recent_is_active": recent_is_active,
            "recent_name": recent_name}
