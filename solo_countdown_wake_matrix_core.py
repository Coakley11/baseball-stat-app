"""Four-cycle solo_countdown_wake mount — diagnostic matrix (app shell or Solo route)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from minimal_component_wake_repro_core import (
    REQUIRED_CYCLES,
    COUNTDOWN_SECONDS,
    RecordStageFn,
    coerce_token,
    init_minimal_wake_session,
    record_delivery,
)

COMPONENT_NAME = "solo_countdown_wake"
SESSION_PREFIX = "_solo_wake_matrix_"


def _session_key(name: str) -> str:
    return f"{SESSION_PREFIX}{name}"


def init_matrix_session(session: dict[str, Any]) -> None:
    session.setdefault(_session_key("callbacks"), [])
    session.setdefault(_session_key("cycles_done"), 0)
    session.setdefault(_session_key("cycle"), 0)
    session.setdefault(_session_key("seen_tokens"), [])
    session.setdefault(_session_key("mount_count"), 0)


def synthetic_room(*, cycle: int, route: bool, draft_id: str | None = None) -> dict[str, Any]:
    deadline = time.time() + float(COUNTDOWN_SECONDS)
    did = (draft_id or "").strip() or ("DIAGROUTE" if route else "DIAGSHELL")
    return {
        "draft_room_id": did,
        "draft_id": did,
        "current_pick_index": cycle,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": COUNTDOWN_SECONDS},
        "_solo_diag_timer_seconds": COUNTDOWN_SECONDS,
    }


def widget_key(*, cycle: int, route: bool, placement: str = "") -> str:
    if placement:
        return f"solo_countdown_wake_diag_{placement.lower()}_{cycle}"
    prefix = "solo_countdown_wake_diag_route" if route else "solo_countdown_wake_diag_shell"
    return f"{prefix}_{cycle}"


def frontend_dir() -> Path:
    from solo_countdown_component import get_component_frontend_dir

    return get_component_frontend_dir()


@dataclass
class CycleRenderResult:
    cycles_done: int
    required_cycles: int
    passed_all: bool
    should_rerun: bool
    widget_key: str
    token: str
    diag: dict[str, Any]
    callbacks: list[dict[str, Any]]
    mount_count: int


def render_one_cycle(
    st: Any,
    session: dict[str, Any],
    *,
    route: bool,
    record_stage: RecordStageFn | None = None,
    draft_id: str | None = None,
    placement: str = "",
    countdown_seconds: int | None = None,
) -> CycleRenderResult:
    from solo_countdown_component import mount_solo_countdown_wake_direct

    init_matrix_session(session)
    cycles_done = int(session.get(_session_key("cycles_done")) or 0)
    cycle = int(session.get(_session_key("cycle")) or 0)
    if cycles_done >= REQUIRED_CYCLES:
        return CycleRenderResult(
            cycles_done=cycles_done,
            required_cycles=REQUIRED_CYCLES,
            passed_all=True,
            should_rerun=False,
            widget_key="done",
            token="",
            diag={},
            callbacks=list(session.get(_session_key("callbacks")) or []),
            mount_count=int(session.get(_session_key("mount_count")) or 0),
        )

    secs = int(countdown_seconds if countdown_seconds is not None else COUNTDOWN_SECONDS)
    room = synthetic_room(cycle=cycle, route=route, draft_id=draft_id)
    if countdown_seconds is not None and countdown_seconds != COUNTDOWN_SECONDS:
        room["timer_deadline"] = time.time() + float(secs)
        room["_solo_diag_timer_seconds"] = secs
        room["config"] = {"timer_seconds": secs}
    key = widget_key(cycle=cycle, route=route, placement=placement)
    session[_session_key("mount_count")] = int(session.get(_session_key("mount_count")) or 0) + 1
    mount_before = cycles_done

    from solo_countdown_component import build_solo_expire_token

    token = build_solo_expire_token(room)
    if record_stage:
        record_stage(
            "component_declaration_loaded",
            {
                "component_name": COMPONENT_NAME,
                "frontend_path": str(frontend_dir()),
                "widget_key": key,
                "expire_token": token,
                "mount_count": session[_session_key("mount_count")],
            },
        )

    def _on_change() -> None:
        raw = st.session_state.get(key)
        if record_stage:
            record_stage(
                "on_change_callback_entry",
                {"widget_key": key, "raw_session_state": repr(raw)[:800]},
            )
            record_stage(
                "session_state_raw_received",
                {
                    "key": key,
                    "raw_type": type(raw).__name__ if raw is not None else "NoneType",
                },
            )
        tok = coerce_token(raw, token)
        if record_stage:
            record_stage("token_coercion_complete", {"token": tok})

        def _rec(source: str, t: str, r: Any) -> bool:
            seen = list(session.get(_session_key("seen_tokens")) or [])
            if t in seen:
                return False
            seen.append(t)
            session[_session_key("seen_tokens")] = seen
            callbacks = list(session.get(_session_key("callbacks")) or [])
            callbacks.append(
                {
                    "ts": time.time(),
                    "source": source,
                    "token": t,
                    "raw_type": type(r).__name__ if r is not None else "NoneType",
                    "raw_repr": str(r)[:500],
                }
            )
            session[_session_key("callbacks")] = callbacks
            session[_session_key("cycles_done")] = len(seen)
            session[_session_key("cycle")] = len(seen)
            if record_stage:
                record_stage("delivery_token_recorded", {"source": source, "token": t, "cycles_done": len(seen)})
            return True

        if _rec("on_change", tok, raw) and record_stage:
            record_stage("on_change_delivery_complete", {"token": tok})

    raw_return = mount_solo_countdown_wake_direct(room, key=key, on_change=_on_change)
    if raw_return is not None:
        tok = coerce_token(raw_return, token)
        if tok and record_stage:
            record_stage(
                "component_return_value_received",
                {"token": tok, "raw_type": type(raw_return).__name__},
            )

    callbacks = list(session.get(_session_key("callbacks")) or [])
    cycles_done = int(session.get(_session_key("cycles_done")) or 0)
    diag = {
        "component_name": COMPONENT_NAME,
        "widget_key": key,
        "expire_token": token,
        "mount_count": session[_session_key("mount_count")],
        "cycles_done": cycles_done,
    }
    should_rerun = cycles_done > mount_before
    return CycleRenderResult(
        cycles_done=cycles_done,
        required_cycles=REQUIRED_CYCLES,
        passed_all=cycles_done >= REQUIRED_CYCLES,
        should_rerun=should_rerun,
        widget_key=key,
        token=token,
        diag=diag,
        callbacks=callbacks,
        mount_count=int(session.get(_session_key("mount_count")) or 0),
    )
