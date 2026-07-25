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


def render_micro_isolation_once(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    location: str,
    record_stage: RecordStageFn | None = None,
    draft_id: str | None = None,
    route: bool = True,
) -> MicroCycleResult:
    """Mount exactly once; retain probe after expiration without starting cycle 1."""
    from solo_countdown_component import build_solo_expire_token, mount_solo_countdown_wake_direct

    note_micro_rerun(session, source=location, entered=True)
    key = micro_widget_key(placement)
    stages: list[str] = []

    def _rec(stage: str, **fields: Any) -> None:
        stages.append(stage)
        if record_stage:
            record_stage(stage, **fields)

    if session.get(COMPLETE_KEY):
        _rec("micro_complete_frozen", {"widget_key": key})
        return MicroCycleResult(
            widget_key=key,
            token=str(session.get(f"{SESSION_PREFIX}token") or ""),
            delivered=bool(session.get(f"{SESSION_PREFIX}delivered")),
            raw_received=bool(session.get(f"{SESSION_PREFIX}raw_received")),
            on_change_fired=bool(session.get(f"{SESSION_PREFIX}on_change")),
            stages=stages,
        )

    try:
        from app_page_generation import current_script_run_id

        mount_run = str(current_script_run_id(session) or "")
    except ImportError:
        mount_run = str(session.get("_live_draft_script_run_id") or "")
    session[MOUNT_RUN_KEY] = session.get(MOUNT_RUN_KEY) or mount_run

    token = str(session.get(f"{SESSION_PREFIX}token") or "") or micro_token(placement)
    session[f"{SESSION_PREFIX}token"] = token
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

            session[EXPIRE_RUN_KEY] = str(current_script_run_id(session) or "")
        except ImportError:
            session[EXPIRE_RUN_KEY] = str(session.get("_live_draft_script_run_id") or "")
        raw = st.session_state.get(key)
        _rec(
            "on_change_callback_entry",
            {"widget_key": key, "raw_session_state": repr(raw)[:800]},
        )
        session[f"{SESSION_PREFIX}on_change"] = True
        _rec(
            "session_state_raw_received",
            {
                "key": key,
                "raw_type": type(raw).__name__ if raw is not None else "NoneType",
            },
        )
        session[f"{SESSION_PREFIX}raw_received"] = raw is not None
        tok = coerce_token(raw, token)
        if tok:
            session[f"{SESSION_PREFIX}delivered"] = True
            session[COMPLETE_KEY] = True
            _rec("on_change_delivery_complete", {"token": tok})

    if not session.get(MOUNTED_KEY):
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
        session[MOUNTED_KEY] = True
    else:
        raw = st.session_state.get(key)
        if raw is not None and not session.get(COMPLETE_KEY):
            _on_change()

    if session.get(COMPLETE_KEY):
        return MicroCycleResult(
            widget_key=key,
            token=token,
            delivered=True,
            raw_received=bool(session.get(f"{SESSION_PREFIX}raw_received")),
            on_change_fired=bool(session.get(f"{SESSION_PREFIX}on_change")),
            stages=stages,
        )

    st.stop()
    return MicroCycleResult(
        widget_key=key,
        token=token,
        delivered=False,
        raw_received=False,
        on_change_fired=False,
        stages=stages,
    )
