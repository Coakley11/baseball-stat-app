"""Minimal Streamlit Cloud repro — v1 component setComponentValue + on_change only."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

COMPONENT_NAME = "minimal_wake_repro"
_FRONTEND_DIR = Path(__file__).resolve().parent / "minimal_wake_repro_component" / "frontend"
_COMPONENT = components.declare_component(
    COMPONENT_NAME,
    path=str(_FRONTEND_DIR),
)

SESSION_CALLBACKS = "_minimal_wake_repro_callbacks"
SESSION_CYCLES_DONE = "_minimal_wake_repro_cycles_done"
SESSION_CYCLE = "_minimal_wake_repro_cycle"
SESSION_SEEN_TOKENS = "_minimal_wake_repro_seen_tokens"
SESSION_LAST_DIAG = "_minimal_wake_repro_last_diag"
SESSION_MOUNT_COUNT = "_minimal_wake_repro_mount_count"
REQUIRED_CYCLES = 4
COUNTDOWN_SECONDS = 5


def _deploy_sha() -> str:
    marker = Path(__file__).resolve().parent / "minimal_wake_repro_deploy.txt"
    if marker.is_file():
        line = marker.read_text(encoding="utf-8").splitlines()[0]
        return line.split("#", 1)[0].strip()[:7]
    return "local"


def _init_session() -> None:
    st.session_state.setdefault(SESSION_CALLBACKS, [])
    st.session_state.setdefault(SESSION_CYCLES_DONE, 0)
    st.session_state.setdefault(SESSION_CYCLE, 0)
    st.session_state.setdefault(SESSION_SEEN_TOKENS, [])
    st.session_state.setdefault(SESSION_MOUNT_COUNT, 0)


def _build_token(cycle: int) -> str:
    deadline = time.time() + float(COUNTDOWN_SECONDS)
    return f"repro|{cycle}|{deadline:.3f}"


def _widget_key(cycle: int) -> str:
    return f"minimal_wake_repro_{cycle}"


def _coerce_token(raw: Any, fallback: str) -> str:
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


def _record_delivery(source: str, token: str, raw: Any) -> bool:
    seen = list(st.session_state.get(SESSION_SEEN_TOKENS) or [])
    if token in seen:
        return False
    seen.append(token)
    st.session_state[SESSION_SEEN_TOKENS] = seen
    callbacks = list(st.session_state.get(SESSION_CALLBACKS) or [])
    callbacks.append(
        {
            "ts": time.time(),
            "source": source,
            "token": token,
            "raw_type": type(raw).__name__ if raw is not None else "NoneType",
            "raw_repr": str(raw)[:500],
        }
    )
    st.session_state[SESSION_CALLBACKS] = callbacks
    st.session_state[SESSION_CYCLES_DONE] = len(seen)
    st.session_state[SESSION_CYCLE] = len(seen)
    return True


def _update_diag(*, key: str, token: str, raw_return: Any) -> None:
    st.session_state[SESSION_LAST_DIAG] = {
        "component_name": COMPONENT_NAME,
        "component_path": str(_FRONTEND_DIR),
        "widget_key": key,
        "expire_token": token,
        "raw_return": raw_return,
        "raw_return_type": type(raw_return).__name__ if raw_return is not None else "",
        "session_state_value": st.session_state.get(key),
        "callback_count": len(st.session_state.get(SESSION_CALLBACKS) or []),
        "cycles_done": int(st.session_state.get(SESSION_CYCLES_DONE) or 0),
        "mount_count": int(st.session_state.get(SESSION_MOUNT_COUNT) or 0),
        "deploy_sha": _deploy_sha(),
    }


_init_session()
st.set_page_config(page_title="Minimal Component Wake Repro", layout="centered")

cycles_done = int(st.session_state.get(SESSION_CYCLES_DONE) or 0)
cycle = int(st.session_state.get(SESSION_CYCLE) or 0)
if cycles_done >= REQUIRED_CYCLES:
    st.success(f"PASS — {REQUIRED_CYCLES} component deliveries received")
    callbacks = list(st.session_state.get(SESSION_CALLBACKS) or [])
    st.metric("Callback count", len(callbacks))
    st.subheader("Received token history")
    st.dataframe(callbacks, use_container_width=True)
    diag = dict(st.session_state.get(SESSION_LAST_DIAG) or {})
    st.subheader("Last diagnostics")
    st.json(diag)
    probe = json.dumps(
        {
            "passed": True,
            "callback_count": len(callbacks),
            "callbacks": callbacks,
            "diag": diag,
        },
        default=str,
    )[:8000]
    st.markdown(
        f'<div id="repro-deploy-build" data-sha="{_deploy_sha()}"></div>'
        f'<div id="repro-result" data-passed="true" data-callbacks="{len(callbacks)}" '
        f'data-component-name="{COMPONENT_NAME}" data-widget-key="done" '
        f'data-payload="{probe.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
    st.stop()

token = _build_token(cycle)
key = _widget_key(cycle)
st.session_state[SESSION_MOUNT_COUNT] = int(st.session_state.get(SESSION_MOUNT_COUNT) or 0) + 1
mount_before = int(st.session_state.get(SESSION_CYCLES_DONE) or 0)


def _on_change() -> None:
    raw = st.session_state.get(key)
    tok = _coerce_token(raw, token)
    _record_delivery("on_change", tok, raw)


raw_return = _COMPONENT(
    expire_token=token,
    key=key,
    default=None,
    on_change=_on_change,
)

if raw_return is not None:
    tok = _coerce_token(raw_return, token)
    if tok:
        _record_delivery("return_value", tok, raw_return)

_update_diag(key=key, token=token, raw_return=raw_return)

if int(st.session_state.get(SESSION_CYCLES_DONE) or 0) > mount_before:
    st.rerun()

st.title("Minimal component wake repro")
st.caption(
    f"Deploy `{_deploy_sha()}` · component `{COMPONENT_NAME}` · "
    f"{COUNTDOWN_SECONDS}s countdown · {REQUIRED_CYCLES} cycles required"
)
col1, col2, col3 = st.columns(3)
col1.metric("Cycle", cycle + 1)
col2.metric("Deliveries", cycles_done)
col3.metric("Callback count", len(st.session_state.get(SESSION_CALLBACKS) or []))

st.write("Active token:", f"`{token}`")
st.write("Widget key:", f"`{key}`")

diag = dict(st.session_state.get(SESSION_LAST_DIAG) or {})
st.subheader("Python diagnostics")
st.json(diag)

callbacks = list(st.session_state.get(SESSION_CALLBACKS) or [])
if callbacks:
    st.subheader("Received token history")
    st.dataframe(callbacks, use_container_width=True)

probe = json.dumps(
    {
        "passed": False,
        "callback_count": len(callbacks),
        "callbacks": callbacks,
        "diag": diag,
    },
    default=str,
)[:8000]
st.markdown(
    f'<div id="repro-deploy-build" data-sha="{_deploy_sha()}"></div>'
    f'<div id="repro-result" data-passed="false" data-callbacks="{len(callbacks)}" '
    f'data-component-name="{COMPONENT_NAME}" data-widget-key="{key}" '
    f'data-payload="{probe.replace(chr(34), chr(39))}"></div>',
    unsafe_allow_html=True,
)
