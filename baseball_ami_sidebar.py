"""Baseball-only AMI sidebar — hard-coded ⚾ Baseball Insight button (not generic Command Center label)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SOURCE_APP = "baseball"
RENDER_MODULE = "baseball_ami_sidebar.py"
ENTRYPOINT_MODULE = "streamlit_app.py"
BASEBALL_AMI_SIDEBAR_CODE_GENERATION = "baseball-ami-sidebar-v3"
EXPECTED_CODE_GENERATION = "baseball-ami-sidebar-v3"


def baseball_insight_button_label() -> str:
    from suite_analytical_question import BASEBALL_INSIGHT_BUTTON_LABEL

    return BASEBALL_INSIGHT_BUTTON_LABEL


def _safe_widget_suffix(text: str) -> str:
    from suite_analytical_question import _safe_widget_suffix

    return _safe_widget_suffix(text)


def _build_marker() -> str:
    try:
        from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

        return f"{SUITE_BUILD_LABEL} · commit `{GIT_COMMIT_SHORT}` · branch `{GIT_BRANCH}`"
    except ImportError:
        return "build marker unavailable"


def _code_status() -> str:
    if BASEBALL_AMI_SIDEBAR_CODE_GENERATION == EXPECTED_CODE_GENERATION:
        return "CURRENT"
    return f"STALE (expected {EXPECTED_CODE_GENERATION!r})"


def _ami_debug_visible(st: Any, session_state: dict[str, Any]) -> bool:
    """True only when the Developer Mode sidebar checkbox is on."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        return developer_mode_checkbox_enabled(st=st)
    except ImportError:
        return bool(session_state.get("app_developer_mode"))


def _render_ami_submit_debug_panel(
    st: Any,
    *,
    source_app: str,
    submit_label: str,
    source_page: str = "",
) -> None:
    """Dev-only diagnostics beside the submit button (?dev=1 or dev_mode)."""
    module_path = str(Path(__file__).resolve())
    status = _code_status()
    st.sidebar.caption(
        "🛠 **AMI submit debug** · "
        f"module `{RENDER_MODULE}` · path `{module_path}` · "
        f"entry `{ENTRYPOINT_MODULE}` · source_app={source_app!r} · "
        f"page={source_page or '—'!r} · label={submit_label!r} · "
        f"code `{BASEBALL_AMI_SIDEBAR_CODE_GENERATION}` → {status} · "
        f"{_build_marker()}"
    )


def render_baseball_insight_sidebar(
    st: Any,
    *,
    source_page: str,
    session_state: dict[str, Any] | None = None,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    source_state_builder: Callable[[], dict[str, Any] | None] | None = None,
    default_question: str = "",
    on_after_send: Callable[[], None] | None = None,
) -> None:
    """Render Baseball Insight sidebar; submit still routes to Command Center internally."""
    from suite_analytical_question import (
        BASEBALL_INSIGHT_SECTION_TITLE,
        build_submit_context,
        submit_analytical_question,
    )

    ss = session_state if session_state is not None else st.session_state
    ss["_suite_runtime_app_id"] = SOURCE_APP
    source_app = SOURCE_APP
    submit_label = baseball_insight_button_label()
    debug_on = _ami_debug_visible(st, ss)

    page_suffix = _safe_widget_suffix(source_page)
    send_gen = int(ss.get(f"_ami_send_gen_{source_app}_{page_suffix}") or 0)
    question_key = f"ami_question_{source_app}_{page_suffix}_{send_gen}"
    submit_key = f"ami_submit_{source_app}_{page_suffix}"

    if debug_on:
        ss["_ami_sidebar_render_debug"] = {
            "module": RENDER_MODULE,
            "entrypoint": ENTRYPOINT_MODULE,
            "source_app_raw": source_app,
            "source_app_resolved": source_app,
            "submit_label": submit_label,
            "code_generation": BASEBALL_AMI_SIDEBAR_CODE_GENERATION,
            "code_status": _code_status(),
            "build_marker": _build_marker(),
        }

    st.sidebar.markdown(f"### {BASEBALL_INSIGHT_SECTION_TITLE}")
    st.sidebar.caption(
        "Ask about players, trades, sleepers, roster weaknesses, strategy, draft picks, "
        "projections, or team decisions."
    )

    last = ss.get("_ami_last_send")
    if isinstance(last, dict) and str(last.get("source_app") or "").strip().lower() == source_app:
        from suite_analytical_question import _recent_duplicate_send

        if _recent_duplicate_send(ss, str(last.get("question_id") or "")):
            st.sidebar.success(
                "Baseball insight request saved. Open Command Center when you're ready to review it."
            )

    question = st.sidebar.text_area(
        "Question",
        value=str(ss.get(question_key) or default_question or "").strip(),
        placeholder="e.g. Is this trend meaningful statistically?",
        height=88,
        key=question_key,
        label_visibility="visible",
    )

    if debug_on:
        _render_ami_submit_debug_panel(
            st,
            source_app=source_app,
            submit_label=submit_label,
            source_page=source_page,
        )

    if st.sidebar.button(
        submit_label,
        key=submit_key,
        use_container_width=True,
        type="primary",
    ):
        q = str(question or "").strip()
        if not q:
            st.sidebar.warning("Enter a question first.")
        else:
            submit_ctx = build_submit_context(
                source_app,
                source_page,
                ss,
                context_extra_builder=context_extra_builder,
            )
            submit_source_state: dict[str, Any] | None = None
            if source_state_builder is not None:
                try:
                    submit_source_state = source_state_builder()
                except Exception:
                    log.exception("AMI source_state builder failed for baseball (%s)", source_page)
            result = submit_analytical_question(
                source_app=source_app,
                source_page=source_page,
                question=q,
                context=submit_ctx,
                source_state=submit_source_state,
                session_state=ss,
            )
            ss["_last_analytical_question"] = result
            ss[f"_ami_send_gen_{source_app}_{page_suffix}"] = send_gen + 1
            if result.get("duplicate"):
                st.sidebar.info(
                    "That baseball insight was already requested recently. "
                    "Open Command Center to review it."
                )
            else:
                st.sidebar.success(
                    "Baseball insight request saved. Open Command Center when you're ready to review it."
                )
            if on_after_send is not None and not result.get("duplicate"):
                try:
                    on_after_send()
                except Exception:
                    log.exception("on_after_send hook failed for baseball (%s)", source_page)
            st.rerun()

    st.sidebar.divider()
