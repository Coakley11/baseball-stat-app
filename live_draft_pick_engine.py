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


def _display_decision_score(val: Any) -> float | None:
    n = _safe_float(val)
    if n is None:
        return None
    return n * 100.0 if n <= 1.5 else n


def _display_player_grade(val: Any) -> float | None:
    n = _safe_float(val)
    if n is None:
        return None
    return n * 100.0 if n <= 1.5 else n


def _position_bucket(pos: str) -> str:
    p = str(pos or "").strip().upper()
    if p in ("BN", "BENCH"):
        return "Bench"
    if p in ("DH", "UTIL"):
        return "UTIL"
    return p


def _category_list(row: dict[str, Any]) -> list[str]:
    cats = row.get("strong_categories_at_pick")
    if isinstance(cats, list):
        return [str(c).strip() for c in cats if str(c).strip()]
    if isinstance(cats, str) and cats.strip():
        return [c.strip() for c in cats.replace("/", ",").split(",") if c.strip()]
    return []


def build_pick_verdict(
    row: Any,
    *,
    gaps: list[str] | None = None,
    pick_no: int | None = None,
) -> str:
    """Short user-facing verdict explaining why this player was chosen over alternatives."""
    if hasattr(row, "to_dict"):
        data = row.to_dict()
    else:
        data = dict(row or {})
    pos = str(data.get("Primary Position") or "")
    bucket = _position_bucket(pos)
    gap_list = [str(g).strip() for g in (gaps or []) if str(g).strip()]
    pick = int(pick_no) if pick_no is not None else int(_safe_float(data.get("Pick")) or 0)
    market = _safe_float(data.get("Market Rank"))
    edge = _safe_float(data.get("Fantasy Edge"))
    dec = _display_decision_score(data.get("Decision Score") or data.get("decision_score_at_pick"))
    fit = _safe_float(data.get("Draft Fit Score") or data.get("roster_fit_score_at_pick"))
    scarcity = _safe_float(data.get("Scarcity Score") or data.get("scarcity_score_at_pick"))
    grade = _display_player_grade(data.get("Expected Fantasy Value"))
    cats = _category_list(data)

    if pick and market and market - pick >= 20:
        edge_txt = f" (+{int(round(edge))} vs market)" if edge and edge > 0 else ""
        return f"Major value pick (+{int(round(market - pick))} vs ADP){edge_txt}."

    if edge is not None and edge >= 30:
        return f"Major value pick (+{int(round(edge))} vs market)."

    if edge is not None and edge >= 15:
        return f"Value pick (+{int(round(edge))} vs market)."

    if dec is not None and dec >= 90:
        return "Highest Decision Score available."

    if gap_list and (pos in gap_list or bucket in gap_list):
        if scarcity is not None and scarcity >= 0.70:
            return f"Best positional fit before scarcity increased ({pos or bucket})."
        if fit is not None and fit >= 1.0:
            return "Best positional fit available."
        return f"Filled {pos or bucket} need."

    if cats and edge is not None and edge >= 8:
        cat_txt = "/".join(cats[:2])
        return f"Added projected {cat_txt} impact (+{int(round(edge))} vs market)."

    if grade is not None and grade >= 85:
        return f"Highest player grade remaining ({grade:.1f})."

    if scarcity is not None and scarcity >= 0.75:
        label = pos or "hitters"
        return f"Highest scarcity among remaining {label}."

    if cats:
        return f"Improved weakest category: {cats[0]}."

    if bucket == "Bench":
        return "Added bench depth."

    if bucket == "UTIL":
        return "Filled utility slot."

    if dec is not None and dec >= 75:
        return f"Strong Decision Score ({dec:.1f})."

    if edge is not None and edge > 0:
        return f"Positive edge (+{int(round(edge))} vs market)."

    if fit is not None and fit >= 1.0:
        return f"Strong roster fit ({fit:.2f})."

    return "Balanced value pick at this slot."


def build_structured_pick_verdict(
    row: dict[str, Any],
    *,
    pick_source: str,
    gaps: list[str] | None = None,
) -> str:
    """User-facing pick verdict for live draft board rows."""
    pick_no = int(_safe_float(row.get("Pick")) or 0) or None
    return build_pick_verdict(row, gaps=gaps, pick_no=pick_no)


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
    session: dict[str, Any] | None = None,
    enrich_pick_context: bool = True,
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
        from live_draft_perf import PHASE_PICK_PICK_ENRICH, live_draft_perf_action
    except ImportError:
        live_draft_perf_action = None  # type: ignore[assignment,misc]
        PHASE_PICK_PICK_ENRICH = "live_draft_pick_enrich"  # type: ignore[misc]

    gaps: list[str] = []

    def _enrich_pick_context() -> None:
        nonlocal gaps
        try:
            from live_draft_category_outlook import player_top_category_strengths

            pool_df = room.get("pool")
            cfg = dict(room.get("config") or {})
            strengths = player_top_category_strengths(player_row, pool_df, config=cfg, max_count=3)
            if strengths:
                snap["strong_categories_at_pick"] = strengths
        except ImportError:
            pass
        try:
            from live_draft_roster_slots import get_remaining_position_needs
            from live_draft_roster_tracker import roster_df_for_team

            gaps = get_remaining_position_needs(roster_df_for_team(room, team), dict(room.get("config") or {}))
            pos = str(player_row.get("Primary Position") or "")
            snap["position_need_at_pick"] = bool(pos and pos in gaps)
        except ImportError:
            pass

    if enrich_pick_context:
        if session is not None and live_draft_perf_action is not None:
            with live_draft_perf_action(session, "pick_enrich", phase=PHASE_PICK_PICK_ENRICH):
                _enrich_pick_context()
        else:
            _enrich_pick_context()

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

    try:
        from live_draft_perf import PHASE_PICK_BOARD_MUTATION, PHASE_PICK_ROSTER_MUTATION, live_draft_perf_action
    except ImportError:
        live_draft_perf_action = None  # type: ignore[assignment,misc]
        PHASE_PICK_BOARD_MUTATION = "live_draft_pick_board_mutation"  # type: ignore[misc]
        PHASE_PICK_ROSTER_MUTATION = "live_draft_pick_roster_mutation"  # type: ignore[misc]

    def _apply_pick_mutations() -> None:
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

    if session is not None and live_draft_perf_action is not None:
        with live_draft_perf_action(session, "board_mutation", phase=PHASE_PICK_BOARD_MUTATION):
            room.setdefault("draft_board", []).append(pick_record)
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
        with live_draft_perf_action(session, "roster_mutation", phase=PHASE_PICK_ROSTER_MUTATION):
            room.setdefault("rosters", {}).setdefault(team, []).append(pick_record)
    else:
        _apply_pick_mutations()
    return True, f"Drafted {player_row.get('fullName', 'player')} to {team}."
