"""Solo Live Draft start validation + diagnostics (setup click path)."""

from __future__ import annotations

from typing import Any

SETUP_VALIDATION_ERROR_KEY = "_live_draft_setup_validation_error"
START_PATH_DIAG_KEY = "_live_draft_start_path_diag"

LIVE_DRAFT_SETUP_ERROR = (
    "Draft picks per team must be greater than or equal to the number of required roster positions."
)


def slots_from_session(session: dict[str, Any] | None) -> dict[str, int]:
    """Read Live Draft roster slot widgets from session (0 is a valid value)."""
    try:
        from live_draft_roster_slots import slots_dict_from_session_widgets

        return slots_dict_from_session_widgets(session)
    except ImportError:
        keys = {
            "C": "live_slot_c",
            "1B": "live_slot_1b",
            "2B": "live_slot_2b",
            "3B": "live_slot_3b",
            "SS": "live_slot_ss",
            "OF": "live_slot_of",
            "DH": "live_slot_dh",
            "P": "live_slot_p",
            "BN": "live_slot_bench",
        }
        defaults = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 5}
        session = session or {}
        out: dict[str, int] = {}
        for pos, key in keys.items():
            if key not in session:
                out[pos] = int(defaults[pos])
                continue
            try:
                out[pos] = int(session[key])
            except (TypeError, ValueError):
                out[pos] = int(defaults[pos])
        return out


def evaluate_live_draft_start_setup(
    session: dict[str, Any] | None,
    *,
    picks_per_team: int | None = None,
    slots: dict[str, Any] | None = None,
    solo_mode: bool = True,
) -> dict[str, Any]:
    """Validate Live Draft setup before room creation. Does not mutate session."""
    from fantasy_roster_validation import (
        LIVE_DRAFT_SETUP_ERROR as _ERR,
        count_bench_slots,
        count_required_starting_positions,
        ensure_bench_slots_for_extra_picks,
        validate_live_draft_setup,
    )

    session = session or {}
    slot_counts = dict(slots) if isinstance(slots, dict) else slots_from_session(session)
    if picks_per_team is None:
        try:
            picks = int(session.get("live_draft_picks_per_team") or 0)
        except (TypeError, ValueError):
            picks = 0
    else:
        picks = int(picks_per_team)

    check = validate_live_draft_setup(picks_per_team=picks, slots=slot_counts)
    required = int(check.get("required_positions") or count_required_starting_positions(slot_counts))
    bench = int(check.get("bench_slots") or count_bench_slots(slot_counts))
    normalized = (
        ensure_bench_slots_for_extra_picks(slot_counts, picks) if check.get("ok") else dict(slot_counts)
    )
    return {
        "ok": bool(check.get("ok")),
        "error": str(check.get("error") or "") if not check.get("ok") else "",
        "canonical_error": _ERR,
        "picks_per_team": picks,
        "required_starting_positions": required,
        "bench_slots": bench,
        "slots": dict(slot_counts),
        "slots_for_room": dict(normalized),
        "solo_mode": bool(solo_mode),
        "extra_picks": int(check.get("extra_picks") or max(0, picks - required)),
    }


def store_setup_validation_error(session: dict[str, Any], message: str) -> None:
    text = str(message or "").strip()
    if text:
        session[SETUP_VALIDATION_ERROR_KEY] = text
    else:
        session.pop(SETUP_VALIDATION_ERROR_KEY, None)


def clear_setup_validation_error(session: dict[str, Any]) -> None:
    session.pop(SETUP_VALIDATION_ERROR_KEY, None)


def peek_setup_validation_error(session: dict[str, Any]) -> str:
    return str(session.get(SETUP_VALIDATION_ERROR_KEY) or "").strip()


def record_start_path_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Admin-only Start Draft click-path diagnostics (not shown to ordinary users)."""
    import time

    diag = dict(session.get(START_PATH_DIAG_KEY) or {})
    diag.update({k: v for k, v in fields.items() if v is not None})
    diag["updated_at"] = time.time()
    session[START_PATH_DIAG_KEY] = diag
    return diag


def render_start_path_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Developer/admin expander for Start Draft path."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return
    diag = dict(session.get(START_PATH_DIAG_KEY) or {})
    if not diag:
        return
    with st.sidebar.expander("Start Draft path (dev)", expanded=False):
        st.json(diag)
