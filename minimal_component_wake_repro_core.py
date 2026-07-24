"""Shared minimal wake repro mount — used by standalone app and Baseball Case A."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import streamlit.components.v1 as components

COMPONENT_NAME = "minimal_wake_repro"
_FRONTEND_DIR = Path(__file__).resolve().parent / "minimal_wake_repro_component" / "frontend"
_COMPONENT = components.declare_component(
    COMPONENT_NAME,
    path=str(_FRONTEND_DIR),
)

REQUIRED_CYCLES = 4
COUNTDOWN_SECONDS = 5

SESSION_CALLBACKS = "_minimal_wake_repro_callbacks"
SESSION_CYCLES_DONE = "_minimal_wake_repro_cycles_done"
SESSION_CYCLE = "_minimal_wake_repro_cycle"
SESSION_SEEN_TOKENS = "_minimal_wake_repro_seen_tokens"
SESSION_LAST_DIAG = "_minimal_wake_repro_last_diag"
SESSION_MOUNT_COUNT = "_minimal_wake_repro_mount_count"


def init_minimal_wake_session(session: dict[str, Any]) -> None:
    session.setdefault(SESSION_CALLBACKS, [])
    session.setdefault(SESSION_CYCLES_DONE, 0)
    session.setdefault(SESSION_CYCLE, 0)
    session.setdefault(SESSION_SEEN_TOKENS, [])
    session.setdefault(SESSION_MOUNT_COUNT, 0)


def build_token(cycle: int, *, countdown_seconds: int = COUNTDOWN_SECONDS) -> str:
    deadline = time.time() + float(countdown_seconds)
    return f"repro|{cycle}|{deadline:.3f}"


def widget_key(cycle: int) -> str:
    return f"minimal_wake_repro_{cycle}"


def coerce_token(raw: Any, fallback: str) -> str:
    if raw is None:
        return fallback
    if isinstance(raw, dict):
        for key in ("token", "expire_token", "value"):
            text = str(raw.get(key) or "").strip()
            if text:
                return text
        return fallback
    text = str(raw).strip()
    return text or fallback


RecordStageFn = Callable[[str, dict[str, Any]], None]


def record_delivery(
    session: dict[str, Any],
    *,
    source: str,
    token: str,
    raw: Any,
    record_stage: RecordStageFn | None = None,
) -> bool:
    seen = list(session.get(SESSION_SEEN_TOKENS) or [])
    if token in seen:
        return False
    seen.append(token)
    session[SESSION_SEEN_TOKENS] = seen
    callbacks = list(session.get(SESSION_CALLBACKS) or [])
    row = {
        "ts": time.time(),
        "source": source,
        "token": token,
        "raw_type": type(raw).__name__ if raw is not None else "NoneType",
        "raw_repr": str(raw)[:500],
    }
    callbacks.append(row)
    session[SESSION_CALLBACKS] = callbacks
    session[SESSION_CYCLES_DONE] = len(seen)
    session[SESSION_CYCLE] = len(seen)
    if record_stage:
        record_stage(
            "delivery_token_recorded",
            {"source": source, "token": token, "cycles_done": len(seen)},
        )
    return True


def update_diag(session: dict[str, Any], *, key: str, token: str, raw_return: Any) -> dict[str, Any]:
    diag = {
        "component_name": COMPONENT_NAME,
        "component_path": str(_FRONTEND_DIR),
        "widget_key": key,
        "expire_token": token,
        "raw_return": raw_return,
        "raw_return_type": type(raw_return).__name__ if raw_return is not None else "",
        "session_state_value": session.get(key),
        "callback_count": len(session.get(SESSION_CALLBACKS) or []),
        "cycles_done": int(session.get(SESSION_CYCLES_DONE) or 0),
        "mount_count": int(session.get(SESSION_MOUNT_COUNT) or 0),
    }
    session[SESSION_LAST_DIAG] = diag
    return diag


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


def render_one_cycle(
    st: Any,
    session: dict[str, Any],
    *,
    record_stage: RecordStageFn | None = None,
    countdown_seconds: int = COUNTDOWN_SECONDS,
    required_cycles: int = REQUIRED_CYCLES,
) -> CycleRenderResult:
    """Mount one countdown cycle using minimal repro component + on_change pattern."""
    init_minimal_wake_session(session)
    cycles_done = int(session.get(SESSION_CYCLES_DONE) or 0)
    cycle = int(session.get(SESSION_CYCLE) or 0)
    if cycles_done >= required_cycles:
        return CycleRenderResult(
            cycles_done=cycles_done,
            required_cycles=required_cycles,
            passed_all=True,
            should_rerun=False,
            widget_key="done",
            token="",
            diag=dict(session.get(SESSION_LAST_DIAG) or {}),
            callbacks=list(session.get(SESSION_CALLBACKS) or []),
        )

    token = build_token(cycle, countdown_seconds=countdown_seconds)
    key = widget_key(cycle)
    session[SESSION_MOUNT_COUNT] = int(session.get(SESSION_MOUNT_COUNT) or 0) + 1
    mount_before = int(session.get(SESSION_CYCLES_DONE) or 0)

    if record_stage:
        record_stage(
            "component_declaration_loaded",
            {
                "component_name": COMPONENT_NAME,
                "widget_key": key,
                "expire_token": token,
                "mount_count": session[SESSION_MOUNT_COUNT],
            },
        )

    def _on_change() -> None:
        raw = st.session_state.get(key)
        if record_stage:
            record_stage(
                "on_change_callback_entry",
                {
                    "widget_key": key,
                    "raw_session_state": repr(raw)[:800],
                },
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
        if record_delivery(session, source="on_change", token=tok, raw=raw, record_stage=record_stage):
            if record_stage:
                record_stage("on_change_delivery_complete", {"token": tok})

    raw_return = _COMPONENT(
        expire_token=token,
        key=key,
        default=None,
        on_change=_on_change,
    )

    if raw_return is not None:
        tok = coerce_token(raw_return, token)
        if tok:
            if record_stage:
                record_stage(
                    "component_return_value_received",
                    {"token": tok, "raw_type": type(raw_return).__name__},
                )
            record_delivery(
                session,
                source="return_value",
                token=tok,
                raw=raw_return,
                record_stage=record_stage,
            )

    diag = update_diag(session, key=key, token=token, raw_return=raw_return)
    cycles_done = int(session.get(SESSION_CYCLES_DONE) or 0)
    should_rerun = cycles_done > mount_before
    return CycleRenderResult(
        cycles_done=cycles_done,
        required_cycles=required_cycles,
        passed_all=cycles_done >= required_cycles,
        should_rerun=should_rerun,
        widget_key=key,
        token=token,
        diag=diag,
        callbacks=list(session.get(SESSION_CALLBACKS) or []),
    )
