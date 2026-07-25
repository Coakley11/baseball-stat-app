"""Single-cycle micro isolation — one token, fixed 10s deadline, no pick processing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from minimal_component_wake_repro_core import coerce_token, RecordStageFn

MICRO_SECONDS = 10
SESSION_PREFIX = "_solo_micro_iso_"
COMPLETE_KEY = f"{SESSION_PREFIX}complete"
MOUNTED_KEY = f"{SESSION_PREFIX}mounted"
MOUNT_RUN_KEY = f"{SESSION_PREFIX}mount_run"
EXPIRE_RUN_KEY = f"{SESSION_PREFIX}expire_run"
RERUN_LOG_KEY = f"{SESSION_PREFIX}rerun_log"
WIDGET_ID_MOUNT_KEY = f"{SESSION_PREFIX}widget_id_mount"
WIDGET_ID_SEND_KEY = f"{SESSION_PREFIX}widget_id_send"


def micro_widget_key(placement: str) -> str:
    slug = placement.strip().lower().replace(" ", "")
    return f"solo_countdown_wake_micro_{slug}"


def micro_token(placement: str) -> str:
    return f"DIAG{placement.upper()}|0|{time.time():.3f}"


def note_micro_rerun(session: dict[str, Any], *, source: str, entered: bool) -> None:
    log = list(session.get(RERUN_LOG_KEY) or [])
    try:
        from app_page_generation import current_script_run_id

        run_id = str(current_script_run_id(session) or "")
    except ImportError:
        run_id = str(session.get("_live_draft_script_run_id") or "")
    log.append(
        {
            "ts": time.time(),
            "source": source,
            "script_run": run_id,
            "diag_branch_entered": entered,
        }
    )
    session[RERUN_LOG_KEY] = log[-80:]


@dataclass
class MicroCycleResult:
    widget_key: str
    token: str
    delivered: bool
    raw_received: bool
    on_change_fired: bool
    stages: list[str]
    should_stop: bool = False


def _session_keys(prefix: str) -> dict[str, str]:
    p = prefix or SESSION_PREFIX
    return {
        "complete": f"{p}complete",
        "mounted": f"{p}mounted",
        "mount_run": f"{p}mount_run",
        "expire_run": f"{p}expire_run",
        "rerun_log": f"{p}rerun_log",
        "widget_id_mount": f"{p}widget_id_mount",
        "widget_id_send": f"{p}widget_id_send",
        "token": f"{p}token",
        "on_change": f"{p}on_change",
        "raw_received": f"{p}raw_received",
        "delivered": f"{p}delivered",
    }


def render_micro_isolation_once(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    location: str,
    record_stage: RecordStageFn | None = None,
    draft_id: str | None = None,
    route: bool = True,
    persistent: bool = False,
    session_prefix: str | None = None,
    widget_key: str | None = None,
    production_room: dict[str, Any] | None = None,
    deliver_callback: Callable[[Any, dict[str, Any], Any, str], None] | None = None,
    production_expire_token: str | None = None,
    production_actionable: bool = True,
    production_delivery_only: bool = False,
) -> MicroCycleResult:
    """Mount exactly once; retain probe after expiration without starting cycle 1."""
    from solo_countdown_component import build_solo_expire_token, mount_solo_countdown_wake_direct

    sk = _session_keys(session_prefix or SESSION_PREFIX)
    if not session_prefix:
        note_micro_rerun(session, source=location, entered=True)
    else:
        log_key = sk["rerun_log"]
        log = list(session.get(log_key) or [])
        try:
            from app_page_generation import current_script_run_id

            run_id = str(current_script_run_id(session) or "")
        except ImportError:
            run_id = str(session.get("_live_draft_script_run_id") or "")
        log.append(
            {
                "ts": time.time(),
                "source": location,
                "script_run": run_id,
                "diag_branch_entered": True,
            }
        )
        session[log_key] = log[-80:]
    key = widget_key or micro_widget_key(placement)
    stages: list[str] = []

    def _rec(stage: str, fields: dict[str, Any] | None = None) -> None:
        stages.append(stage)
        if record_stage:
            record_stage(stage, fields or {})

    if production_room is not None:
        from solo_countdown_component import build_solo_expire_token, mount_solo_countdown_wake_with_token

        token = (
            production_expire_token
            if production_expire_token is not None
            else build_solo_expire_token(production_room)
        )
        session[sk["token"]] = token
        mounted_token_key = f"{sk['mounted']}_token"
        mount_sig_key = f"{sk['mounted']}_sig"
        prior_sig = str(session.get(mount_sig_key) or "")
        sig = f"{token}|actionable={1 if production_actionable else 0}"
        first_mount = not session.get(sk["mounted"])

        def _prod_on_change() -> None:
            try:
                from app_page_generation import current_script_run_id

                session[sk["expire_run"]] = str(current_script_run_id(session) or "")
            except ImportError:
                session[sk["expire_run"]] = str(session.get("_live_draft_script_run_id") or "")
            raw = st.session_state.get(key)
            _rec(
                "on_change_callback_entry",
                {"widget_key": key, "raw_session_state": repr(raw)[:800]},
            )
            _rec(
                "session_state_raw_received",
                {"key": key, "raw_type": type(raw).__name__ if raw is not None else "NoneType"},
            )
            if deliver_callback is not None:
                deliver_callback(st, session, raw, key)

        if production_delivery_only and session.get(sk["mounted"]):
            raw = st.session_state.get(key)
            if raw is not None:
                _prod_on_change()
                return MicroCycleResult(
                    widget_key=key,
                    token=token,
                    delivered=False,
                    raw_received=True,
                    on_change_fired=True,
                    stages=stages,
                    should_stop=False,
                )

        if first_mount:
            _rec(
                "component_declaration_loaded",
                {
                    "component_name": "solo_countdown_wake",
                    "widget_key": key,
                    "expire_token": token,
                    "mount_location": location,
                    "placement": placement,
                    "actionable": production_actionable,
                },
            )
        elif prior_sig != sig:
            _rec(
                "component_props_updated",
                {
                    "widget_key": key,
                    "expire_token": token,
                    "actionable": production_actionable,
                    "prior_sig": prior_sig[:120],
                },
            )
        mount_solo_countdown_wake_with_token(
            production_room,
            key=key,
            expire_token=token,
            actionable=production_actionable,
            on_change=_prod_on_change,
        )
        session[sk["mounted"]] = True
        session[mounted_token_key] = token
        session[mount_sig_key] = sig
        raw = st.session_state.get(key)
        if raw is not None:
            _prod_on_change()

        return MicroCycleResult(
            widget_key=key,
            token=token,
            delivered=False,
            raw_received=raw is not None,
            on_change_fired=False,
            stages=stages,
            should_stop=False,
        )

    if session.get(sk["complete"]):
        _rec("micro_complete_frozen", {"widget_key": key})
        return MicroCycleResult(
            widget_key=key,
            token=str(session.get(sk["token"]) or ""),
            delivered=bool(session.get(sk["delivered"])),
            raw_received=bool(session.get(sk["raw_received"])),
            on_change_fired=bool(session.get(sk["on_change"])),
            stages=stages,
            should_stop=False,
        )

    try:
        from app_page_generation import current_script_run_id

        mount_run = str(current_script_run_id(session) or "")
    except ImportError:
        mount_run = str(session.get("_live_draft_script_run_id") or "")
    session[sk["mount_run"]] = session.get(sk["mount_run"]) or mount_run

    token = str(session.get(sk["token"]) or "") or micro_token(placement)
    session[sk["token"]] = token
    deadline = time.time() + float(MICRO_SECONDS)
    did = (draft_id or "").strip() or f"DIAG{placement.upper()}"
    room = {
        "draft_room_id": did,
        "draft_id": did,
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": MICRO_SECONDS},
        "_solo_diag_timer_seconds": MICRO_SECONDS,
    }

    def _on_change() -> None:
        try:
            from app_page_generation import current_script_run_id

            session[sk["expire_run"]] = str(current_script_run_id(session) or "")
        except ImportError:
            session[sk["expire_run"]] = str(session.get("_live_draft_script_run_id") or "")
        raw = st.session_state.get(key)
        _rec(
            "on_change_callback_entry",
            {"widget_key": key, "raw_session_state": repr(raw)[:800]},
        )
        session[sk["on_change"]] = True
        _rec(
            "session_state_raw_received",
            {
                "key": key,
                "raw_type": type(raw).__name__ if raw is not None else "NoneType",
            },
        )
        session[sk["raw_received"]] = raw is not None
        tok = coerce_token(raw, token)
        if tok:
            session[sk["delivered"]] = True
            session[sk["complete"]] = True
            _rec("on_change_delivery_complete", {"token": tok})

    if not session.get(sk["mounted"]):
        _rec(
            "component_declaration_loaded",
            {
                "component_name": "solo_countdown_wake",
                "widget_key": key,
                "expire_token": token,
                "mount_location": location,
                "placement": placement,
            },
        )
        mount_solo_countdown_wake_direct(room, key=key, on_change=_on_change)
        session[sk["mounted"]] = True
    else:
        raw = st.session_state.get(key)
        if raw is not None and not session.get(sk["complete"]):
            _on_change()

    if session.get(sk["complete"]):
        return MicroCycleResult(
            widget_key=key,
            token=token,
            delivered=True,
            raw_received=bool(session.get(sk["raw_received"])),
            on_change_fired=bool(session.get(sk["on_change"])),
            stages=stages,
            should_stop=False,
        )

    return MicroCycleResult(
        widget_key=key,
        token=token,
        delivered=False,
        raw_received=False,
        on_change_fired=False,
        stages=stages,
        should_stop=False if persistent else True,
    )
