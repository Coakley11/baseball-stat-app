"""Durable Continue Saved Draft / Replace and Start New Draft operations.

Button clicks must leave a visible receipt and never silently no-op after a rerun.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

OP_RECEIPT_KEY = "_live_draft_resumable_op_receipt"
OP_PENDING_KEY = "_live_draft_resumable_op_pending"
OP_UI_FLASH_KEY = "_live_draft_resumable_op_flash"
CONTINUE_PENDING = "continue_saved"
REPLACE_CONFIRM_PENDING = "replace_confirm"
REPLACE_EXECUTE_PENDING = "replace_execute"


def _pid(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return str(session.get("auth_user_id") or session.get("_suite_auth_user_id") or "").strip()


def _lifecycle(session: dict[str, Any]) -> str:
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        return str(resolve_live_draft_lifecycle(session) or "")
    except ImportError:
        return ""


def new_attempt_id() -> str:
    return uuid.uuid4().hex[:12]


def get_op_receipt(session: dict[str, Any]) -> dict[str, Any]:
    blob = session.get(OP_RECEIPT_KEY)
    return dict(blob) if isinstance(blob, dict) else {}


def note_op_step(
    session: dict[str, Any],
    step: str,
    *,
    ok: bool = True,
    detail: str = "",
    **extra: Any,
) -> dict[str, Any]:
    receipt = get_op_receipt(session)
    if not receipt:
        receipt = {
            "attempt_id": new_attempt_id(),
            "started_at": time.time(),
        }
    steps = list(receipt.get("steps") or [])
    steps.append({"step": step, "ok": bool(ok), "detail": str(detail or ""), "ts": time.time()})
    receipt["steps"] = steps[-40:]
    receipt["last_completed_step"] = step
    receipt["last_ok"] = bool(ok)
    if detail:
        receipt["last_detail"] = str(detail)[:400]
    for key, val in extra.items():
        if val is not None:
            receipt[key] = val
    receipt["updated_at"] = time.time()
    session[OP_RECEIPT_KEY] = receipt
    return receipt


def begin_op(
    session: dict[str, Any],
    *,
    action: str,
    button_label: str,
    widget_key: str,
    click_detected: bool = True,
    confirmation_accepted: bool = False,
) -> dict[str, Any]:
    slot = None
    try:
        from live_draft_resumable_slot import get_resumable_live_draft_slot

        slot = get_resumable_live_draft_slot(session)
    except ImportError:
        slot = session.get("resumable_live_draft_slot")
        if not isinstance(slot, dict):
            slot = None

    life_before = _lifecycle(session)
    commissioner = False
    try:
        from shared_draft_permissions import is_canonical_commissioner

        commissioner = bool(is_canonical_commissioner(session, None))
    except ImportError:
        commissioner = False

    receipt = {
        "attempt_id": new_attempt_id(),
        "action": action,
        "button_label": button_label,
        "widget_key": widget_key,
        "click_detected": bool(click_detected),
        "confirmation_accepted": bool(confirmation_accepted),
        "canonical_user_id": _pid(session),
        "commissioner_authorized": commissioner,
        "resumable_slot_id": str((slot or {}).get("draft_id") or (slot or {}).get("room_code") or "") or None,
        "saved_draft_id": str((slot or {}).get("draft_id") or "") or None,
        "saved_room_id": str((slot or {}).get("room_id") or (slot or {}).get("draft_id") or "") or None,
        "saved_room_code": str((slot or {}).get("room_code") or "").upper() or None,
        "lifecycle_before": life_before,
        "lifecycle_after": None,
        "full_app_rerun_requested": False,
        "exception": None,
        "failure_message": None,
        "success": None,
        "steps": [],
        "started_at": time.time(),
    }
    session[OP_RECEIPT_KEY] = receipt
    note_op_step(session, "click_detected", button_label=button_label, widget_key=widget_key)
    if confirmation_accepted:
        note_op_step(session, "confirmation_accepted")
    return receipt


def set_op_flash(session: dict[str, Any], message: str, *, kind: str = "info") -> None:
    session[OP_UI_FLASH_KEY] = {"message": str(message), "kind": kind, "ts": time.time()}


def consume_op_flash(session: dict[str, Any]) -> dict[str, Any] | None:
    flash = session.pop(OP_UI_FLASH_KEY, None)
    return dict(flash) if isinstance(flash, dict) else None


def finish_op(
    session: dict[str, Any],
    *,
    success: bool,
    message: str = "",
    lifecycle_target: str = "",
    rerun: bool = False,
) -> dict[str, Any]:
    receipt = note_op_step(
        session,
        "finished" if success else "failed",
        ok=success,
        detail=message,
        success=success,
        failure_message=None if success else message,
        lifecycle_after=_lifecycle(session),
        lifecycle_target=lifecycle_target or None,
        full_app_rerun_requested=bool(rerun),
    )
    if message:
        set_op_flash(session, message, kind="success" if success else "error")
    return receipt


def request_full_app_rerun(st: Any, session: dict[str, Any], *, reason: str) -> None:
    note_op_step(session, "full_app_rerun_requested", detail=reason, full_app_rerun_requested=True)
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=f"resumable_op:{reason}")
    except Exception:
        pass
    st.rerun()
    st.stop()


def on_continue_saved_click() -> None:
    import streamlit as st

    begin_op(
        st.session_state,
        action=CONTINUE_PENDING,
        button_label="Continue Saved Draft",
        widget_key="live_draft_continue_saved_btn",
    )
    st.session_state[OP_PENDING_KEY] = CONTINUE_PENDING
    set_op_flash(st.session_state, "Opening saved draft…", kind="info")


def on_replace_request_click() -> None:
    import streamlit as st

    begin_op(
        st.session_state,
        action=REPLACE_CONFIRM_PENDING,
        button_label="Replace and Start New Draft",
        widget_key="live_draft_replace_saved_start_btn",
    )
    st.session_state["_live_draft_replace_confirm_pending"] = True
    st.session_state[OP_PENDING_KEY] = REPLACE_CONFIRM_PENDING
    set_op_flash(
        st.session_state,
        "Confirm replacement below — the saved draft will be kept until a new room is created.",
        kind="info",
    )


def on_replace_confirm_click() -> None:
    import streamlit as st

    begin_op(
        st.session_state,
        action=REPLACE_EXECUTE_PENDING,
        button_label="Confirm Replace & Start",
        widget_key="live_draft_replace_saved_confirm_btn",
        confirmation_accepted=True,
    )
    st.session_state.pop("_live_draft_replace_confirm_pending", None)
    st.session_state.pop("_live_draft_start_replace_resumable_pending", None)
    st.session_state.pop("_live_draft_start_replace_resumable_message", None)
    st.session_state[OP_PENDING_KEY] = REPLACE_EXECUTE_PENDING
    set_op_flash(st.session_state, "Preparing a replacement draft…", kind="info")


def on_replace_cancel_click() -> None:
    import streamlit as st

    st.session_state.pop("_live_draft_replace_confirm_pending", None)
    note_op_step(st.session_state, "replace_cancelled")
    set_op_flash(st.session_state, "Kept the saved draft.", kind="info")


def _clear_force_setup_for_resume(session: dict[str, Any]) -> None:
    """force_setup must not erase a just-restored Resume Lobby."""
    session.pop("_live_draft_force_setup_after_delete", None)
    # Keep deleting=done for tombstone checks, but do not treat it as a wipe signal
    # while an explicit resume/replace op is in flight.
    if session.get("_live_draft_resume_lobby") or session.get(OP_PENDING_KEY):
        if str(session.get("_live_draft_deleting") or "").strip().lower() == "done":
            # Leave the flag — lifecycle will ignore wipe when resume lobby is set.
            pass


def execute_continue_saved(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    note_op_step(session, "load_resumable_slot")
    try:
        from live_draft_resumable_slot import continue_saved_draft, get_resumable_live_draft_slot
    except ImportError as exc:
        finish_op(session, success=False, message=f"Continue unavailable: {exc}")
        return {"ok": False, "error": "import", "message": str(exc)}

    slot = get_resumable_live_draft_slot(session)
    if not slot:
        finish_op(session, success=False, message="Draft could not be opened: no saved draft to continue.")
        return {"ok": False, "error": "no_slot", "message": "No saved draft to continue."}

    note_op_step(
        session,
        "slot_loaded",
        saved_draft_id=slot.get("draft_id"),
        saved_room_code=slot.get("room_code"),
    )
    _clear_force_setup_for_resume(session)
    note_op_step(session, "hydrate_start")
    result = continue_saved_draft(session, st=st)
    if not result.get("ok"):
        finish_op(
            session,
            success=False,
            message=f"Draft could not be opened: {result.get('message') or result.get('error') or 'unknown error'}",
        )
        return result

    # Persist Resume Lobby before any rerun — required for refresh survival.
    session["_live_draft_resume_lobby"] = True
    note_op_step(session, "resume_lobby_installed", ok=True)
    note_op_step(session, "hydrate_complete", ok=True)
    life = _lifecycle(session)
    finish_op(
        session,
        success=True,
        message="Resume Lobby opened — waiting for reserved teams before Continue Draft.",
        lifecycle_target="waiting_shared_lobby",
        rerun=True,
    )
    note_op_step(session, "lifecycle_after_continue", detail=life, lifecycle_after=life)
    return result


def build_replacement_live_room(
    session: dict[str, Any],
    *,
    slot: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Build a fresh Pick-1 room from sticky setup prefs / prior slot config."""
    import pandas as pd

    prior = slot.get("room") if isinstance(slot.get("room"), dict) else {}
    cfg = dict(prior.get("config") or {})
    summary = dict(slot.get("summary") or {})

    def _int(key: str, *alts: Any, default: int = 0) -> int:
        for src in (session.get(key), cfg.get(key), *alts):
            try:
                if src is not None and str(src).strip() != "":
                    return int(src)
            except (TypeError, ValueError):
                continue
        return int(default)

    num_teams = _int("live_draft_team_count", cfg.get("num_teams"), summary.get("num_teams"), default=2)
    picks = _int("live_draft_picks_per_team", cfg.get("picks_per_team"), default=4)
    timer = _int("live_draft_timer_seconds", cfg.get("timer_seconds"), default=60)
    if timer <= 0:
        # Timer widget may be a label — fall back to config / 60.
        label = str(session.get("live_draft_timer") or "").strip().lower()
        if "30" in label:
            timer = 30
        elif "90" in label:
            timer = 90
        elif "120" in label or "2 min" in label:
            timer = 120
        else:
            timer = int(cfg.get("timer_seconds") or 60)

    teams = [str(t).strip() for t in (cfg.get("teams") or prior.get("teams") or []) if str(t).strip()]
    if len(teams) < num_teams:
        teams = [f"Team {chr(ord('A') + i)}" for i in range(num_teams)]
    teams = teams[:num_teams]
    host_team = str(
        session.get("live_draft_host_team_pick")
        or cfg.get("your_team")
        or cfg.get("user_team")
        or teams[0]
    ).strip() or teams[0]

    # Minimal pool so create does not require the full Streamlit start handler.
    prior_pool = prior.get("pool")
    if isinstance(prior_pool, pd.DataFrame) and not prior_pool.empty:
        pool = prior_pool.copy()
    else:
        records = prior.get("pool_records") if isinstance(prior.get("pool_records"), list) else []
        if records:
            pool = pd.DataFrame(records)
        else:
            pool = pd.DataFrame(
                [
                    {
                        "playerID": f"rp{i}",
                        "fullName": f"Replacement Player {i}",
                        "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "OF", "DH"][i % 8],
                    }
                    for i in range(max(40, num_teams * picks + 8))
                ]
            )

    try:
        from live_draft_state import live_draft_init_room

        config = {
            "league_name": str(session.get("live_draft_league_name") or cfg.get("league_name") or "My Fantasy League"),
            "num_teams": num_teams,
            "picks_per_team": picks,
            "draft_type": "snake",
            "scoring_type": str(session.get("live_draft_scoring") or cfg.get("scoring_type") or "Roto (5x5)"),
            "timer_seconds": timer,
            "teams": teams,
            "user_team": host_team,
            "your_team": host_team,
            "slots": dict(cfg.get("slots") or {}),
            "draft_setup_mode": "shared_multiplayer" if slot.get("is_shared") or slot.get("room_code") else "solo",
            "projection_style": str(session.get("live_draft_proj_style") or cfg.get("projection_style") or "Balanced"),
            "projection_window": _int("live_draft_proj_window", cfg.get("projection_window"), default=3),
        }
        room = live_draft_init_room(config, pool)
    except Exception:
        # Fallback shape matching create path.
        order = []
        pick_n = 1
        for rnd in range(1, picks + 1):
            seq = teams if rnd % 2 == 1 else list(reversed(teams))
            for team in seq:
                order.append({"Pick": pick_n, "Round": rnd, "Team": team})
                pick_n += 1
        room = {
            "draft_room_id": f"R{uuid.uuid4().hex[:6].upper()}",
            "status": "not_started",
            "current_pick_index": 0,
            "config": {
                "num_teams": num_teams,
                "picks_per_team": picks,
                "timer_seconds": timer,
                "teams": teams,
                "user_team": host_team,
                "your_team": host_team,
                "draft_setup_mode": "shared_multiplayer",
            },
            "teams": teams,
            "pick_order": order,
            "draft_board": [],
            "rosters": {t: [] for t in teams},
            "drafted_player_ids": [],
            "pool": pool,
        }
    room["status"] = "not_started"
    room["current_pick_index"] = 0
    room["draft_board"] = []
    return room, host_team


def execute_replace_transactional(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Create the new Shared/Solo room first; only then tombstone the old saved room."""
    try:
        from live_draft_resumable_slot import get_resumable_live_draft_slot
        from live_draft_setup_mode import (
            SETUP_MODE_SHARED,
            finalize_shared_room_create,
            get_preferred_next_draft_mode,
            is_shared_multiplayer_intent,
            set_live_draft_setup_mode,
        )
    except ImportError as exc:
        finish_op(session, success=False, message=f"Replace unavailable: {exc}")
        return {"ok": False, "error": "import", "message": str(exc)}

    slot = get_resumable_live_draft_slot(session)
    if not slot:
        finish_op(session, success=False, message="Draft could not be replaced: no saved draft found.")
        return {"ok": False, "error": "no_slot", "message": "No saved draft found."}

    # Keep an immutable copy so create failure cannot lose the saved draft.
    slot_backup = dict(slot)
    old_code = str(slot.get("room_code") or "").strip().upper()
    old_draft_id = str(slot.get("draft_id") or "").strip()
    old_room_id = str(slot.get("room_id") or old_draft_id).strip()
    note_op_step(
        session,
        "replace_slot_validated",
        saved_draft_id=old_draft_id,
        saved_room_code=old_code,
    )

    # Capture sticky prefs (do not clear slot yet).
    prefer_shared = bool(slot.get("is_shared")) or bool(old_code)
    try:
        prefer_shared = prefer_shared or is_shared_multiplayer_intent(session)
        if not prefer_shared:
            prefer_shared = get_preferred_next_draft_mode(session) == SETUP_MODE_SHARED
    except Exception:
        pass
    note_op_step(session, "prefs_captured", detail="shared" if prefer_shared else "solo")

    try:
        new_room, host_team = build_replacement_live_room(session, slot=slot)
    except Exception as exc:
        session["resumable_live_draft_slot"] = slot_backup
        finish_op(
            session,
            success=False,
            message=f"Draft could not be replaced: could not build new room ({exc}). Saved draft kept.",
        )
        return {"ok": False, "error": "build_failed", "message": str(exc), "slot_kept": True}

    note_op_step(session, "provisional_room_built", draft_id=new_room.get("draft_room_id"))
    _clear_force_setup_for_resume(session)

    if prefer_shared:
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        note_op_step(session, "shared_room_create_start")
        code, err = finalize_shared_room_create(
            session, new_room, host_team=host_team
        )
        if not code:
            session["resumable_live_draft_slot"] = slot_backup
            finish_op(
                session,
                success=False,
                message=(
                    f"Draft could not be replaced: {err or 'shared room create failed'}. "
                    "Saved draft kept."
                ),
            )
            return {"ok": False, "error": "create_failed", "message": err, "slot_kept": True}
        note_op_step(session, "shared_room_create_verified", room_code=code, ok=True)
        new_code = code
        # Ensure Pick 1 lobby is active in session even if create helper left status parked.
        live = session.get("live_draft_room")
        if not isinstance(live, dict):
            live = new_room
            session["live_draft_room"] = live
        live["status"] = str(live.get("status") or "not_started") or "not_started"
        live["current_pick_index"] = 0
        live["draft_board"] = []
        session["active_shared_draft_room_code"] = code
    else:
        new_room["status"] = "in_progress"
        new_room["current_pick_index"] = 0
        new_room["draft_board"] = []
        session["live_draft_room"] = new_room
        new_code = ""
        note_op_step(session, "solo_room_activated", draft_id=new_room.get("draft_room_id"))

    # Only after new room succeeds: tombstone old + clear slot.
    note_op_step(session, "tombstone_old_start", saved_room_code=old_code)
    try:
        from live_draft_termination import persist_durable_tombstones

        persist_durable_tombstones(
            session, draft_id=old_draft_id, room_id=old_room_id, room_code=old_code
        )
    except ImportError:
        pass
    if old_code and old_code != new_code:
        try:
            from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

            doc = load_shared_room(old_code)
            if isinstance(doc, dict):
                doc["status"] = "deleted"
                blob = doc.get("room")
                if isinstance(blob, dict):
                    blob["status"] = "deleted"
                get_shared_room_store().save(bump_revision(doc))
        except Exception as exc:
            note_op_step(session, "tombstone_old_warning", ok=False, detail=str(exc)[:200])
    try:
        from live_draft_resumable_slot import clear_resumable_live_draft_slot

        clear_resumable_live_draft_slot(session)
    except ImportError:
        session.pop("resumable_live_draft_slot", None)
    note_op_step(session, "old_slot_cleared", ok=True)

    session.pop("_live_draft_resume_lobby", None)
    session.pop("_live_draft_resume_reserved_teams", None)
    try:
        from live_draft_creation_trace import protect_new_room

        protect_new_room(session)
    except ImportError:
        pass

    finish_op(
        session,
        success=True,
        message=(
            f"Replacement draft ready"
            + (f" — join code **{new_code}**" if new_code else "")
            + ". Opening new lobby at Pick 1…"
        ),
        lifecycle_target="waiting_shared_lobby" if prefer_shared else "active_draft",
        rerun=True,
    )
    return {
        "ok": True,
        "new_room_code": new_code,
        "old_room_code": old_code,
        "room": new_room,
    }


def process_pending_resumable_ops(session: dict[str, Any], *, st: Any) -> bool:
    """Run at top of Live Draft page. Returns True if caller should stop (rerun issued)."""
    pending = str(session.pop(OP_PENDING_KEY, "") or "").strip()
    if not pending:
        return False

    if pending == CONTINUE_PENDING:
        set_op_flash(session, "Opening saved draft…", kind="info")
        result = execute_continue_saved(session, st=st)
        if result.get("ok"):
            request_full_app_rerun(st, session, reason="continue_saved_success")
        # Failure: leave flash/receipt for UI; do not wipe slot.
        return False

    if pending == REPLACE_CONFIRM_PENDING:
        # Confirmation UI is rendered in setup; nothing to execute yet.
        note_op_step(session, "awaiting_replace_confirmation")
        return False

    if pending == REPLACE_EXECUTE_PENDING:
        set_op_flash(session, "Preparing a replacement draft…", kind="info")
        result = execute_replace_transactional(session, st=st)
        if result.get("ok"):
            request_full_app_rerun(st, session, reason="replace_success")
        return False

    note_op_step(session, "unknown_pending", ok=False, detail=pending)
    return False


def render_op_receipt_panel(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode: durable Continue/Replace click receipt."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        if not (session.get("app_developer_mode") or session.get("_suite_developer_mode_user")):
            return
    receipt = get_op_receipt(session)
    if not receipt:
        return
    with st.expander("Resumable draft operation receipt (Developer Mode)", expanded=not receipt.get("success")):
        rows = [
            ("button_label", receipt.get("button_label")),
            ("widget_key", receipt.get("widget_key")),
            ("click_detected", receipt.get("click_detected")),
            ("confirmation_accepted", receipt.get("confirmation_accepted")),
            ("canonical_user_id", receipt.get("canonical_user_id")),
            ("commissioner_authorized", receipt.get("commissioner_authorized")),
            ("resumable_slot_id", receipt.get("resumable_slot_id")),
            ("saved_draft_id", receipt.get("saved_draft_id")),
            ("saved_room_id", receipt.get("saved_room_id")),
            ("saved_room_code", receipt.get("saved_room_code")),
            ("operation_attempt_id", receipt.get("attempt_id")),
            ("last_completed_step", receipt.get("last_completed_step")),
            ("lifecycle_before", receipt.get("lifecycle_before")),
            ("lifecycle_after", receipt.get("lifecycle_after")),
            ("full_app_rerun_requested", receipt.get("full_app_rerun_requested")),
            ("success", receipt.get("success")),
            ("failure_message", receipt.get("failure_message")),
            ("exception", receipt.get("exception")),
        ]
        for key, val in rows:
            st.caption(f"**{key}:** `{val}`")
        steps = receipt.get("steps") or []
        if steps:
            st.code("\n".join(f"{s.get('step')} ok={s.get('ok')} {s.get('detail') or ''}" for s in steps[-20:]))
