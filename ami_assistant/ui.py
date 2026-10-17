"""Minimal "Ask AMI" sidebar panel — question box, answer, context line, loading/error states.

It is a Streamlit fragment, so asking a question reruns only the panel (AMI's own work is
well under a second) instead of the whole page. It sits just above the existing ⚾ Baseball
Insight sender, which still hands longer analyses to Command Center. Read-only: it renders
answers and stores only this conversation in the user's own session.
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as _streamlit

from ami_assistant.context import build_ami_context
from ami_assistant.conversation import clear_conversation, load_conversation

log = logging.getLogger(__name__)

LAST_KEY = "_ami_assistant_last"
QUESTION_KEY = "ami_assistant_question"
FORM_KEY = "ami_assistant_form"
DEFAULT_PLACEHOLDER = "e.g. Compare Aaron Judge and Juan Soto"


def suggested_questions(page: str) -> tuple[str, ...]:
    """The page's suggested questions (page_help metadata) — for the placeholder now, and for the
    future phone header entry / question chips. Every one is tested to route to a real answer."""
    from ami_assistant.page_help import PAGE_HELP

    ph = PAGE_HELP.get(page)
    return tuple(ph.questions) if ph else ()


def placeholder_for(page: str) -> str:
    questions = suggested_questions(page)
    return f"e.g. {questions[0]}" if questions else DEFAULT_PLACEHOLDER


def _debug_visible(st: Any) -> bool:
    try:
        from baseball_ami_sidebar import _ami_debug_visible

        return bool(_ami_debug_visible(st, st.session_state))
    except Exception:
        return False


def _ask(st: Any, question: str, active_page: str, yearly_df: Any, entitlement: Any = None) -> None:
    from ami_assistant.engine import ask

    resp = ask(question, session_state=st.session_state, active_page=active_page, yearly_df=yearly_df,
               entitlement=entitlement)
    st.session_state[LAST_KEY] = {
        "question": question,
        "answer": resp.answer,
        "grounding_label": resp.grounding_label,
        "basis": resp.basis,
        "intent": resp.intent,
        "tools": resp.tools,
        "timings_ms": resp.timings_ms,
        "used_context": resp.used_context,
        "error": resp.error,
    }


def _clear(session: Any) -> None:
    # A click callback runs before the rerun, so the panel redraws already cleared.
    clear_conversation(session)
    session.pop(LAST_KEY, None)


def _panel_body(st: Any, active_page: str, yearly_df: Any, entitlement: Any = None) -> None:
    st.markdown("### 💬 Ask AMI")
    st.caption("Instant answers from this app's stats and help pages. AMI is read-only — it never changes your drafts or teams.")
    ctx = build_ami_context(st.session_state, active_page)
    st.caption(f"Looking at: {ctx.summary()}")

    with st.form(FORM_KEY, clear_on_submit=True, border=False):
        question = st.text_input(
            "Ask AMI",
            key=QUESTION_KEY,
            placeholder=placeholder_for(ctx.page),
            max_chars=500,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask AMI", type="primary", width="stretch")
    if submitted:
        q = str(question or "").strip()
        if not q:
            st.warning("Type a question first.")
        else:
            with st.spinner("AMI is looking that up…"):
                _ask(st, q, active_page, yearly_df, entitlement)

    last = st.session_state.get(LAST_KEY)
    if isinstance(last, dict) and last.get("answer"):
        box = st.container(border=True)
        box.markdown(f"**You asked:** {last['question']}")
        if last.get("error"):
            box.error(last["answer"])
        else:
            box.markdown(last["answer"])
            meta = [x for x in (last.get("grounding_label"), *(last.get("basis") or [])) if x]
            if meta:
                box.caption(" · ".join(meta))
        conv = load_conversation(st.session_state)
        earlier = conv.turns[:-1][-3:]
        if earlier:
            with st.expander("Earlier in this conversation", expanded=False):
                for turn in reversed(earlier):
                    st.markdown(f"**{turn.question}**")
                    st.markdown(turn.answer)
        st.button("Clear conversation", key="ami_assistant_clear", width="stretch",
                  on_click=_clear, args=(st.session_state,))
        if _debug_visible(st):
            with st.expander("AMI diagnostics (Developer Mode)", expanded=False):
                st.json({k: last.get(k) for k in ("intent", "tools", "timings_ms", "used_context")})
    st.divider()


@_streamlit.fragment
def _panel(active_page: str, yearly_df: Any, entitlement: Any = None) -> None:
    """Runs as a fragment, so asking reruns only this panel. Fragment-only reruns skip the
    caller's try/except, hence the guard here too."""
    try:
        _panel_body(_streamlit, active_page, yearly_df, entitlement)
    except Exception:
        log.exception("AMI assistant panel failed on %s", active_page)
        _streamlit.caption("AMI is unavailable right now.")


def render_ami_assistant_panel(st: Any, *, active_page: str, yearly_df: Any = None, entitlement: Any = None) -> None:
    """Never breaks the page: any failure shows a short notice instead. ``entitlement``: the
    page gate's own snapshot for this run (see tools.registry.entitlement_block)."""
    try:
        with st.sidebar:
            _panel(active_page, yearly_df, entitlement)
    except Exception:
        log.exception("AMI assistant panel failed on %s", active_page)
        try:
            st.sidebar.caption("AMI is unavailable right now.")
        except Exception:
            pass
