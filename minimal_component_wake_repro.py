"""Minimal Streamlit Cloud repro — v1 component setComponentValue + on_change only."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from minimal_component_wake_repro_core import (
    COMPONENT_NAME,
    REQUIRED_CYCLES,
    COUNTDOWN_SECONDS,
    SESSION_CALLBACKS,
    SESSION_CYCLES_DONE,
    SESSION_CYCLE,
    SESSION_LAST_DIAG,
    SESSION_MOUNT_COUNT,
    init_minimal_wake_session,
    render_one_cycle,
)


def _deploy_sha() -> str:
    marker = Path(__file__).resolve().parent / "minimal_wake_repro_deploy.txt"
    if marker.is_file():
        line = marker.read_text(encoding="utf-8").splitlines()[0]
        return line.split("#", 1)[0].strip()[:7]
    return "local"


init_minimal_wake_session(st.session_state)
st.set_page_config(page_title="Minimal Component Wake Repro", layout="centered")

result = render_one_cycle(st, st.session_state)

if result.passed_all:
    st.success(f"PASS — {REQUIRED_CYCLES} component deliveries received")
    callbacks = result.callbacks
    st.metric("Callback count", len(callbacks))
    st.subheader("Received token history")
    st.dataframe(callbacks, use_container_width=True)
    st.subheader("Last diagnostics")
    st.json(result.diag)
    probe = json.dumps(
        {
            "passed": True,
            "callback_count": len(callbacks),
            "callbacks": callbacks,
            "diag": result.diag,
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

if result.should_rerun:
    st.rerun()

st.title("Minimal component wake repro")
st.caption(
    f"Deploy `{_deploy_sha()}` · component `{COMPONENT_NAME}` · "
    f"{COUNTDOWN_SECONDS}s countdown · {REQUIRED_CYCLES} cycles required"
)
col1, col2, col3 = st.columns(3)
col1.metric("Cycle", int(st.session_state.get(SESSION_CYCLE) or 0) + 1)
col2.metric("Deliveries", result.cycles_done)
col3.metric("Callback count", len(result.callbacks))

st.write("Active token:", f"`{result.token}`")
st.write("Widget key:", f"`{result.widget_key}`")

st.subheader("Python diagnostics")
st.json(result.diag)

if result.callbacks:
    st.subheader("Received token history")
    st.dataframe(result.callbacks, use_container_width=True)

probe = json.dumps(
    {
        "passed": False,
        "callback_count": len(result.callbacks),
        "callbacks": result.callbacks,
        "diag": result.diag,
    },
    default=str,
)[:8000]
st.markdown(
    f'<div id="repro-deploy-build" data-sha="{_deploy_sha()}"></div>'
    f'<div id="repro-result" data-passed="false" data-callbacks="{len(result.callbacks)}" '
    f'data-component-name="{COMPONENT_NAME}" data-widget-key="{result.widget_key}" '
    f'data-payload="{probe.replace(chr(34), chr(39))}"></div>',
    unsafe_allow_html=True,
)
