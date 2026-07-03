"""Pure live draft pick helpers — no Streamlit imports or side effects."""

from __future__ import annotations

from typing import Any

from live_draft_timer_logic import live_draft_clear_timer, live_draft_current_slot, live_draft_reset_timer

_PICK_SOURCE_LABELS: dict[str, str] = {
    "rec_card": "Draft Assistant Pick",
    "recommendation_card": "Draft Assistant Pick",
    "live_draft_room": "Live Draft Pick",
    "queue": "Draft Queue Pick",
    "draft_queue": "Draft Queue Pick",
    "autopick": "Auto Pick",
    "auto": "Auto Pick",
    "manual": "Manual Pick",
    "shared_room_commit": "Live Draft Pick",
    "host": "Host Pick",
    "balanced recommendation": "Auto Pick",
}


def normalize_pick_source_label(source: str) -> str:
    raw = str(source or "").strip()
    if not raw:
        return "Manual Pick"
    key = raw.lower().replace(" ", "_")
    if key in _PICK_SOURCE_LABELS:
        return _PICK_SOURCE_LABELS[key]
    friendly = {v.lower(): v for v in _PICK_SOURCE_LABELS.values()}
    if raw.lower() in friendly:
        return friendly[raw.lower()]
    if raw.endswith(" Pick"):
        return raw
    return raw.replace("_", " ").title()


def _safe_float(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def build_structured_pick_verdict(
    row: dict[str, Any],
    *,
    pick_source: str,
    gaps: list[str] | None = None,
) -> str:
    """User-facing pick verdict — source label plus decision-support prose."""
    label = normalize_pick_source_label(pick_source)
    pos = str(row.get("Primary Position") or "")
    gap_list = list(gaps or [])
    clauses: list[str] = []
    if gap_list and pos and pos in gap_list:
        clauses.append(f"Filled remaining {pos} need")
    elif row.get("position_need_at_pick"):
        clauses.append(f"Filled remaining {pos} need")
    cats = row.get("strong_categories_at_pick")
    if isinstance(cats, list) and cats:
        clauses.append(f"improved {'/'.join(str(c) for c in cats[:2])} production")
    elif isinstance(cats, str) and cats.strip():
        clauses.append(f"improved {cats} production")
    dec = _safe_float(row.get("Decision Score")) or _safe_float(row.get("decision_score_at_pick"))
    if dec is not None:
        if dec >= 0.75:
            clauses.append("Strong decision")
        elif dec >= 0.55:
            clauses.append("Solid decision")
        else:
            clauses.append("Lower decision score relative to alternatives")
    fit = _safe_float(row.get("Draft Fit Score")) or _safe_float(row.get("roster_fit_score_at_pick"))
    if fit is not None and fit >= 0.72 and not (gap_list and pos in gap_list):
        if not any("Filled" in c for c in clauses):
            clauses.append("Strong roster fit without an open positional need")
    if not clauses:
        clauses.append("Added projected value to the roster")
    return f"{label}: {'. '.join(clauses[:3])}."


def live_draft_bump_sync_revision(room: dict[str, Any], event: str = "pick") -> None:
    import time

    meta = room.setdefault("meta", {})
    sync = meta.setdefault("sync", {"revision": 0, "storage_backend": "session_state"})
    sync["revision"] = int(sync.get("revision", 0)) + 1
    sync["last_event"] = event
    sync["updated_at"] = time.time()


def live_draft_make_pick(
    room: dict[str, Any],
    player_row: dict[str, Any],
    verdict: str = "Manual pick",
    *,
    pick_source: str = "",
    snapshot: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    slot = live_draft_current_slot(room)
    if slot is None:
        return False, "Draft is already complete."
    team = slot["Team"]
    pid = str(player_row.get("playerID", ""))
    if pid in set(room.get("drafted_player_ids", [])):
        return False, "That player has already been drafted."
    pick_record = dict(player_row)
    snap = dict(snapshot or {})
    for key in (
        "Decision Score",
        "Draft Fit Score",
        "Scarcity Score",
        "Positional Fit",
        "Category Need Bonus",
        "Survival Probability",
    ):
        if key not in snap and key in player_row:
            snap[key] = player_row.get(key)
    try:
        from live_draft_category_outlook import player_top_category_strengths

        pool_df = room.get("pool")
        cfg = dict(room.get("config") or {})
        strengths = player_top_category_strengths(player_row, pool_df, config=cfg, max_count=3)
        if strengths:
            snap["strong_categories_at_pick"] = strengths
    except ImportError:
        pass
    gaps: list[str] = []
    try:
        from live_draft_roster_slots import get_remaining_position_needs
        from live_draft_roster_tracker import roster_df_for_team

        gaps = get_remaining_position_needs(roster_df_for_team(room, team), dict(room.get("config") or {}))
        pos = str(player_row.get("Primary Position") or "")
        snap["position_need_at_pick"] = bool(pos and pos in gaps)
    except ImportError:
        pass
    source_label = normalize_pick_source_label(pick_source or verdict or "manual")
    if not verdict or str(verdict).startswith("Draft ("):
        verdict = build_structured_pick_verdict(
            {**player_row, **snap},
            pick_source=source_label,
            gaps=gaps,
        )
    pick_record.update(
        {
            "Round": slot["Round"],
            "Pick": slot["Pick"],
            "Fantasy Team": team,
            "Pick Verdict": verdict,
            "pick_source": source_label,
            "decision_score_at_pick": snap.get("Decision Score"),
            "roster_fit_score_at_pick": snap.get("Draft Fit Score"),
            "scarcity_score_at_pick": snap.get("Scarcity Score"),
            "position_need_at_pick": snap.get("position_need_at_pick"),
            "strong_categories_at_pick": snap.get("strong_categories_at_pick"),
        }
    )
    room.setdefault("draft_board", []).append(pick_record)
    room.setdefault("rosters", {}).setdefault(team, []).append(pick_record)
    room.setdefault("drafted_player_ids", []).append(pid)
    room["current_pick_index"] = int(room.get("current_pick_index", 0)) + 1
    live_draft_bump_sync_revision(room, event="pick")
    if room.get("meta"):
        room["meta"].setdefault("turn_model", {})["current_pick_index"] = room["current_pick_index"]
    if room["current_pick_index"] >= len(room.get("pick_order", [])):
        room["status"] = "complete"
        live_draft_clear_timer(room)
    else:
        live_draft_reset_timer(room)
    return True, f"Drafted {player_row.get('fullName', 'player')} to {team}."
