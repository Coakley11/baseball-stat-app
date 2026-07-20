"""Solo Live Draft start validation + diagnostics (setup click path)."""

from __future__ import annotations

from typing import Any

SETUP_VALIDATION_ERROR_KEY = "_live_draft_setup_validation_error"
START_PATH_DIAG_KEY = "_live_draft_start_path_diag"

LIVE_DRAFT_SETUP_ERROR = (
    "Draft picks per team must be greater than or equal to the number of required roster positions."
)


# Same product defaults the Live Draft setup number_inputs / Start handler use when a
# widget key is absent. Do not default missing keys to 0 — that under-counts starters
# and can fail-open the picks-vs-positions gate.
_SLOT_PRODUCT_DEFAULTS: dict[str, int] = {
    "C": 1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 3,
    "DH": 1,
    "P": 0,
    "BN": 5,
}


def slots_from_session(session: dict[str, Any] | None) -> dict[str, int]:
    """Read Live Draft roster slot widgets from session (0 is a valid value when set)."""
    session = session or {}
    try:
        from live_draft_roster_slots import LIVE_SLOT_WIDGET_KEYS, session_slot_count

        return {
            pos: session_slot_count(session, key, _SLOT_PRODUCT_DEFAULTS.get(pos, 0))
            for pos, key in LIVE_SLOT_WIDGET_KEYS.items()
        }
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
        out: dict[str, int] = {}
        for pos, key in keys.items():
            default = int(_SLOT_PRODUCT_DEFAULTS.get(pos, 0))
            if key not in session:
                out[pos] = default
                continue
            try:
                out[pos] = int(session[key])
            except (TypeError, ValueError):
                out[pos] = default
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


def _session_get(session: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    """Read session values without relying on Mapping.get (AppTest SessionState edge cases)."""
    if session is None:
        return default
    try:
        if key in session:
            return session[key]
    except Exception:
        pass
    try:
        return session[key]  # type: ignore[index]
    except Exception:
        return default


def picks_per_team_from_session(session: dict[str, Any] | None) -> int:
    """Read picks-per-team from the same widget key the Start handler uses."""
    session = session or {}
    raw = _session_get(session, "live_draft_picks_per_team", None)
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    try:
        from user_page_preferences import live_draft_setup_number_default

        return int(live_draft_setup_number_default(session, "live_draft_picks_per_team", 4))
    except Exception:
        return 4


def fail_closed_setup_check(
    session: dict[str, Any] | None,
    *,
    picks_per_team: int | None = None,
    slots: dict[str, Any] | None = None,
    solo_mode: bool = True,
) -> dict[str, Any]:
    """Validate setup; never fail-open if helpers are missing."""
    try:
        return evaluate_live_draft_start_setup(
            session,
            picks_per_team=picks_per_team,
            slots=slots,
            solo_mode=solo_mode,
        )
    except ImportError:
        pass
    try:
        from fantasy_roster_validation import (
            LIVE_DRAFT_SETUP_ERROR as _ERR,
            ensure_bench_slots_for_extra_picks,
            validate_live_draft_setup,
        )

        session = session or {}
        slot_counts = dict(slots) if isinstance(slots, dict) else slots_from_session(session)
        picks = int(picks_per_team) if picks_per_team is not None else picks_per_team_from_session(session)
        check = validate_live_draft_setup(picks_per_team=picks, slots=slot_counts)
        normalized = (
            ensure_bench_slots_for_extra_picks(slot_counts, picks)
            if check.get("ok")
            else dict(slot_counts)
        )
        return {
            "ok": bool(check.get("ok")),
            "error": str(check.get("error") or "") if not check.get("ok") else "",
            "canonical_error": _ERR,
            "picks_per_team": picks,
            "required_starting_positions": int(check.get("required_positions") or 0),
            "bench_slots": int(check.get("bench_slots") or 0),
            "slots": dict(slot_counts),
            "slots_for_room": dict(normalized),
            "solo_mode": bool(solo_mode),
            "extra_picks": int(check.get("extra_picks") or 0),
        }
    except ImportError:
        slot_counts = dict(slots) if isinstance(slots, dict) else slots_from_session(session)
        picks = int(picks_per_team) if picks_per_team is not None else picks_per_team_from_session(session)
        return {
            "ok": False,
            "error": LIVE_DRAFT_SETUP_ERROR,
            "canonical_error": LIVE_DRAFT_SETUP_ERROR,
            "picks_per_team": picks,
            "required_starting_positions": 0,
            "bench_slots": 0,
            "slots": dict(slot_counts),
            "slots_for_room": dict(slot_counts),
            "solo_mode": bool(solo_mode),
            "extra_picks": 0,
        }


def gate_start_new_live_draft_click(session: dict[str, Any]) -> dict[str, Any]:
    """Start New Live Draft on_click gate: validate before arming pending / replace.

    Invalid setups store the exact error and never arm create or replace.
    Valid setups with a resumable slot arm replace confirmation only.
    Otherwise arms ``_start_live_draft_pending``.
    """
    try:
        from live_draft_setup_mode import is_solo_draft_mode

        solo_mode = bool(is_solo_draft_mode(session))
    except ImportError:
        solo_mode = True

    picks = picks_per_team_from_session(session)
    slots = slots_from_session(session)
    check = fail_closed_setup_check(
        session,
        picks_per_team=picks,
        slots=slots,
        solo_mode=solo_mode,
    )
    record_start_path_diagnostics(
        session,
        button_clicked=True,
        picks_per_team=int(check.get("picks_per_team") or picks),
        required_starting_positions=int(check.get("required_starting_positions") or 0),
        roster_slots=dict(check.get("slots") or slots),
        validation_ok=bool(check.get("ok")),
        validation_error=str(check.get("error") or ""),
        solo_mode=solo_mode,
        draft_creation_attempted=False,
        gate="on_start_new_live_draft",
    )
    if not check.get("ok"):
        err = str(check.get("error") or LIVE_DRAFT_SETUP_ERROR)
        store_setup_validation_error(session, err)
        session.pop("_start_live_draft_pending", None)
        session.pop("_live_draft_start_replace_resumable_pending", None)
        record_start_path_diagnostics(
            session,
            final_status="setup_validation_blocked",
            draft_creation_attempted=False,
        )
        return {
            "armed": False,
            "replace_pending": False,
            "ok": False,
            "error": err,
            "check": check,
        }

    clear_setup_validation_error(session)
    try:
        from live_draft_resumable_slot import warn_if_starting_replaces_resumable

        warn = warn_if_starting_replaces_resumable(session)
        if warn and not _session_get(session, "_live_draft_start_replace_resumable_ok"):
            session["_live_draft_start_replace_resumable_pending"] = True
            session["_live_draft_start_replace_resumable_message"] = warn.get("message")
            session.pop("_start_live_draft_pending", None)
            record_start_path_diagnostics(
                session,
                final_status="replace_confirmation_required",
                draft_creation_attempted=False,
            )
            return {
                "armed": False,
                "replace_pending": True,
                "ok": True,
                "error": "",
                "check": check,
            }
        session.pop("_live_draft_start_replace_resumable_ok", None)
        session.pop("_live_draft_start_replace_resumable_pending", None)
        session.pop("_live_draft_start_replace_resumable_message", None)
    except ImportError:
        pass

    session["_start_live_draft_mode"] = "new"
    session["_start_live_draft_pending"] = True
    session.pop("_simulator_to_live_show_confirm", None)
    record_start_path_diagnostics(
        session,
        final_status="pending_armed",
        draft_creation_attempted=False,
    )
    return {
        "armed": True,
        "replace_pending": False,
        "ok": True,
        "error": "",
        "check": check,
    }


def record_start_path_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Admin-only Start Draft click-path diagnostics (not shown to ordinary users)."""
    import time

    raw = _session_get(session, START_PATH_DIAG_KEY, None)
    diag = dict(raw) if isinstance(raw, dict) else {}
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
