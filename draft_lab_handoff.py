"""Apply completed Live Draft Room settings to Draft Simulation Test Mode."""

from __future__ import annotations

from typing import Any

from draft_lab_state import PENDING_DRAFT_LAB_HANDOFF_KEY, stage_draft_lab_handoff_settings

DRAFT_LAB_HANDOFF_DIAG_KEY = "_draft_lab_handoff_diag"


def _lab_format_from_live(scoring: str) -> str:
    return "5x5 Roto" if "Roto" in str(scoring) else "Points League"


def _safe_int(val: Any, default: int | None = None) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def extract_live_room_lab_settings(room: dict[str, Any] | None, session: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read draft-lab-relevant settings from a completed live draft room."""
    session = session or {}
    cfg = dict(room.get("config") or {}) if isinstance(room, dict) else {}
    teams = list(room.get("teams") or []) if isinstance(room, dict) else []
    team_count = _safe_int(cfg.get("num_teams"))
    if team_count is None and teams:
        team_count = len(teams)
    if team_count is None:
        team_count = _safe_int(session.get("live_draft_team_count"))

    picks = _safe_int(cfg.get("picks_per_team"))
    if picks is None:
        picks = _safe_int(session.get("live_draft_picks_per_team"))

    window = _safe_int(cfg.get("projection_window"))
    if window is None:
        window = _safe_int(session.get("live_draft_proj_window"))

    style = str(cfg.get("projection_style") or session.get("live_draft_proj_style") or "").strip()
    scoring = str(cfg.get("scoring_type") or cfg.get("fantasy_format") or session.get("live_draft_scoring") or "").strip()

    board = room.get("draft_board") or [] if isinstance(room, dict) else []
    board_pick_count = len(board) if isinstance(board, list) else 0
    expected = (team_count or 0) * (picks or 0) if team_count and picks else 0

    return {
        "draft_lab_window": window if window in (3, 4, 5) else None,
        "draft_lab_scoring_type": _lab_format_from_live(scoring) if scoring else None,
        "draft_lab_projection_style": style or None,
        "draft_lab_picks_per_team": picks if picks is not None else None,
        "draft_lab_team_count": team_count,
        "team_names": [str(t) for t in teams],
        "room_code": str(session.get("active_shared_draft_room_code") or "").strip().upper() or None,
        "session_id": str(room.get("draft_room_id") or "").strip() if isinstance(room, dict) else None,
        "board_pick_count": board_pick_count,
        "expected_pick_count": expected or None,
    }


def _settings_keys_from_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    if extracted.get("draft_lab_window") is not None:
        keys["draft_lab_window"] = int(extracted["draft_lab_window"])
    if extracted.get("draft_lab_scoring_type"):
        keys["draft_lab_scoring_type"] = extracted["draft_lab_scoring_type"]
        keys["draft_lab_format"] = extracted["draft_lab_scoring_type"]
    if extracted.get("draft_lab_projection_style"):
        keys["draft_lab_projection_style"] = extracted["draft_lab_projection_style"]
    if extracted.get("draft_lab_picks_per_team") is not None:
        keys["draft_lab_picks_per_team"] = int(extracted["draft_lab_picks_per_team"])
    if extracted.get("draft_lab_team_count") is not None:
        keys["draft_lab_team_count"] = int(extracted["draft_lab_team_count"])
    return keys


def live_room_lab_settings_keys(session: dict[str, Any]) -> dict[str, Any]:
    """Session keys for page transfer Live Draft Room -> Draft Lab."""
    room = session.get("live_draft_room")
    extracted = extract_live_room_lab_settings(room if isinstance(room, dict) else None, session)
    return _settings_keys_from_extracted(extracted)


def record_draft_lab_handoff_diagnostics(session: dict[str, Any], extracted: dict[str, Any], *, loaded: bool) -> None:
    diag = {
        "draft_lab_source": "live_draft_room" if loaded else "",
        "draft_lab_source_room_code": extracted.get("room_code"),
        "draft_lab_source_session_id": extracted.get("session_id"),
        "draft_lab_loaded_from_live_room": loaded,
        "draft_lab_live_projection_window": extracted.get("draft_lab_window"),
        "draft_lab_live_fantasy_format": extracted.get("draft_lab_scoring_type"),
        "draft_lab_live_projection_style": extracted.get("draft_lab_projection_style"),
        "draft_lab_live_picks_per_team": extracted.get("draft_lab_picks_per_team"),
        "draft_lab_live_team_count": extracted.get("draft_lab_team_count"),
        "draft_lab_lab_projection_window_after_handoff": (session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {}).get("draft_lab_window")
        if isinstance(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY), dict)
        else session.get("draft_lab_window"),
        "draft_lab_lab_fantasy_format_after_handoff": (session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {}).get("draft_lab_scoring_type")
        if isinstance(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY), dict)
        else session.get("draft_lab_scoring_type"),
        "draft_lab_lab_projection_style_after_handoff": (session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {}).get("draft_lab_projection_style")
        if isinstance(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY), dict)
        else session.get("draft_lab_projection_style"),
        "draft_lab_lab_picks_per_team_after_handoff": (session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {}).get("draft_lab_picks_per_team")
        if isinstance(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY), dict)
        else session.get("draft_lab_picks_per_team"),
        "draft_lab_lab_team_count_after_handoff": (session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {}).get("draft_lab_team_count")
        if isinstance(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY), dict)
        else session.get("draft_lab_team_count"),
        "draft_lab_board_pick_count": extracted.get("board_pick_count"),
        "draft_lab_expected_pick_count": extracted.get("expected_pick_count"),
    }
    session[DRAFT_LAB_HANDOFF_DIAG_KEY] = diag
    try:
        from draft_lab_analysis import draft_lab_roster_team_options

        session["_draft_lab_team_names"] = draft_lab_roster_team_options(extracted.get("team_names") or [])
    except ImportError:
        pass
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(session, **diag)
    except ImportError:
        pass


def apply_live_draft_handoff_to_session(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    """Stage Draft Lab widget keys from a completed live draft room (apply before widgets)."""
    extracted = extract_live_room_lab_settings(room, session)
    stage_draft_lab_handoff_settings(session, _settings_keys_from_extracted(extracted))
    session["live_draft_room"] = room
    record_draft_lab_handoff_diagnostics(session, extracted, loaded=True)
    handoff_meta = {
        "source": "Live Draft Room",
        "team_count": extracted.get("draft_lab_team_count"),
        "picks_per_team": extracted.get("draft_lab_picks_per_team"),
        "projection_window": extracted.get("draft_lab_window"),
        "fantasy_format": extracted.get("draft_lab_scoring_type"),
        "projection_style": extracted.get("draft_lab_projection_style"),
        "team_names": extracted.get("team_names") or [],
        "room_code": extracted.get("room_code"),
        "session_id": extracted.get("session_id"),
        "draft_room_id": extracted.get("session_id"),
        "board_pick_count": extracted.get("board_pick_count"),
        "expected_pick_count": extracted.get("expected_pick_count"),
    }
    return handoff_meta
