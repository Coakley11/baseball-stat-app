"""Ask AMI — the app's one question box (U5).

One assistant, one conversation, shown in one place per device:

- desktop: the sidebar panel;
- phone: an "Ask AMI" bar at the top of every page (the sidebar copy is hidden there).

It answers right away from the read-only AMI engine (``ami_assistant.engine.ask``). Under an
answer about the user's data, **Get full analysis** hands the same question to Command Center
(Applied Mathematical Intelligence) — but only when the user presses it: the host passes that
handoff in as ``full_analysis`` (``baseball_ami_sidebar.submit_baseball_insight``), so this
package never imports the cloud-writing pipeline and a quick answer never saves anything.

Each surface is a Streamlit fragment, so asking reruns only the panel, never the page's
analytics. The conversation lives only in this user's session.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import streamlit as _streamlit

from ami_assistant.capabilities import APP_DATA, EXTERNAL_CURRENT
from ami_assistant.context import build_ami_context
from ami_assistant.conversation import clear_conversation, load_conversation

log = logging.getLogger(__name__)

LAST_KEY = "_ami_assistant_last"
PENDING_KEY = "_ami_assistant_pending_question"  # a suggested question waiting to be asked
FULL_ANALYSIS_KEY = "_ami_assistant_full_analysis"  # the last handoff's outcome (this session only)
QUESTION_KEY = "ami_assistant_question"
FORM_KEY = "ami_assistant_form"
SIDEBAR_ROOT_KEY = "ami_sidebar_panel"
PHONE_ROOT_KEY = "ami_phone_entry"
PHONE_PREFIX = "m_"  # widget keys of the phone surface (same conversation, distinct widgets)
DEFAULT_PLACEHOLDER = "e.g. Compare Aaron Judge and Juan Soto"
MAX_SUGGESTIONS = 3
# Answers that aren't analysis of the user's data: product help, refused instructions, a
# question back to the user. Full analysis isn't offered under these.
NO_FULL_ANALYSIS_INTENTS = frozenset({"action_request", "clarify", "capabilities"})
# A tool refused for access or plan reasons: Get full analysis must not become a way around that.
REFUSED_CODES = frozenset({"not_your_team", "unknown_team", "not_entitled", "entitlement_loading"})
FULL_ANALYSIS_HELP = ("Sends this question, with this page's context, to Command Center for a deeper written "
                      "analysis. That saves the request to your account; quick answers here are never saved.")

# (question, page) -> the submit result ({"duplicate": bool, ...}); supplied by the host app.
FullAnalysis = Callable[[str, str], dict]


def suggested_questions(page: str) -> tuple[str, ...]:
    """The page's suggested questions (page_help metadata). Every one is tested to route to a
    real answer; the panel offers the first few as one-tap questions."""
    from ami_assistant.page_help import PAGE_HELP

    ph = PAGE_HELP.get(page)
    return tuple(ph.questions) if ph else ()


def placeholder_for(page: str) -> str:
    questions = suggested_questions(page)
    return f"e.g. {questions[0]}" if questions else DEFAULT_PLACEHOLDER


def full_analysis_offered(last: Any) -> bool:
    """Offer Command Center only under an answer about data (the app's, the user's league, or a
    question AMI's data can't cover) — not under help, refusals or a clarifying question."""
    if not (isinstance(last, dict) and bool(last.get("answer")) and not last.get("error")):
        return False
    refused = any(isinstance(t, dict) and t.get("error_code") in REFUSED_CODES for t in last.get("tools") or [])
    return (last.get("grounding") in (APP_DATA, EXTERNAL_CURRENT) and last.get("intent") not in NO_FULL_ANALYSIS_INTENTS
            and not refused)


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
        "page": active_page,
        "answer": resp.answer,
        "grounding": resp.grounding,
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
    session.pop(FULL_ANALYSIS_KEY, None)


def _queue(session: Any, question: str) -> None:
    session[PENDING_KEY] = question


def queue_question(session: Any, question: str) -> None:
    """Ask Ask AMI ``question`` on the next run (e.g. from Home's Ask card): the panel asks it into
    the one shared conversation, and the phone bar opens with the answer. Use as a click callback."""
    _queue(session, str(question or "").strip())


def _send_full_analysis(st: Any, full_analysis: FullAnalysis, last: dict[str, Any]) -> None:
    """The explicit handoff: the user pressed Get full analysis."""
    question, page = str(last.get("question") or ""), str(last.get("page") or "")
    try:
        result = full_analysis(question, page) or {}
    except Exception:
        log.exception("AMI full-analysis handoff failed on %s", page)
        st.session_state[FULL_ANALYSIS_KEY] = {"question": question, "failed": True}
        return
    st.session_state[FULL_ANALYSIS_KEY] = {"question": question, "duplicate": bool(result.get("duplicate"))}


def _full_analysis_status(st: Any, last: dict[str, Any]) -> None:
    done = st.session_state.get(FULL_ANALYSIS_KEY)
    if not isinstance(done, dict) or done.get("question") != last.get("question"):
        return
    if done.get("failed"):
        st.error("Couldn't send this to Command Center right now. Try again in a moment.")
    elif done.get("duplicate"):
        st.info("You already asked for this analysis a moment ago. Open Command Center to review it.")
    else:
        st.success("Full analysis requested. Open Command Center when you're ready to review it.")


def _panel_body(st: Any, active_page: str, yearly_df: Any, entitlement: Any = None, *,
                full_analysis: FullAnalysis | None = None, surface: str = "sidebar") -> None:
    prefix = PHONE_PREFIX if surface == "phone" else ""
    ss = st.session_state
    if surface == "sidebar":
        st.markdown("### 💬 Ask AMI")
    st.caption("Ask about players, stats, your league or how to use a page. Quick answers come from this app's own "
               "data; AMI is read-only and never changes your drafts or teams.")
    ctx = build_ami_context(ss, active_page)
    st.caption(f"Looking at: {ctx.summary()}")

    with st.form(f"{prefix}{FORM_KEY}", clear_on_submit=True, border=False):
        question = st.text_input(
            "Ask AMI",
            key=f"{prefix}{QUESTION_KEY}",
            placeholder=placeholder_for(ctx.page),
            max_chars=500,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask AMI", type="primary", width="stretch")
    pending = ss.pop(PENDING_KEY, None)
    q = str(pending or (question if submitted else "") or "").strip()
    if submitted and not q:
        st.warning("Type a question first.")
    elif q:
        with st.spinner("AMI is looking that up…"):
            _ask(st, q, active_page, yearly_df, entitlement)

    last = ss.get(LAST_KEY)
    has_answer = isinstance(last, dict) and bool(last.get("answer"))
    suggestions = suggested_questions(ctx.page)[:MAX_SUGGESTIONS]
    if suggestions and not has_answer:
        st.caption("Try:")
        for i, s in enumerate(suggestions):
            st.button(s, key=f"{prefix}ami_suggest_{i}", type="tertiary", on_click=_queue, args=(ss, s))

    if has_answer:
        box = st.container(border=True)
        box.markdown(f"**You asked:** {last['question']}")
        if last.get("error"):
            box.error(last["answer"])
        else:
            box.markdown(last["answer"])
            meta = [x for x in (last.get("grounding_label"), *(last.get("basis") or [])) if x]
            if meta:
                box.caption(" · ".join(meta))
        if full_analysis is not None and full_analysis_offered(last):
            # One send per answer: once requested, the button is spent (a failed send can be retried).
            done = ss.get(FULL_ANALYSIS_KEY)
            sent = isinstance(done, dict) and done.get("question") == last.get("question") and not done.get("failed")
            # on_click runs before the redraw, so the button is already spent when the panel draws again.
            st.button("Full analysis requested" if sent else "Get full analysis", key=f"{prefix}ami_full_analysis",
                      width="stretch", help=FULL_ANALYSIS_HELP, disabled=sent,
                      on_click=_send_full_analysis, args=(st, full_analysis, dict(last)))
            _full_analysis_status(st, last)
        conv = load_conversation(ss)
        earlier = conv.turns[:-1][-3:]
        if earlier:
            with st.expander("Earlier in this conversation", expanded=False):
                for turn in reversed(earlier):
                    st.markdown(f"**{turn.question}**")
                    st.markdown(turn.answer)
        st.button("Clear conversation", key=f"{prefix}ami_assistant_clear", width="stretch",
                  on_click=_clear, args=(ss,))
        if _debug_visible(st):
            with st.expander("AMI diagnostics (Developer Mode)", expanded=False):
                st.json({k: last.get(k) for k in ("intent", "tools", "timings_ms", "used_context")})
    if surface == "sidebar":
        st.divider()


@_streamlit.fragment
def _panel(active_page: str, yearly_df: Any, entitlement: Any = None, full_analysis: FullAnalysis | None = None,
           surface: str = "sidebar") -> None:
    """Runs as a fragment, so asking reruns only this panel. Fragment-only reruns skip the
    caller's try/except, hence the guard here too."""
    try:
        _panel_body(_streamlit, active_page, yearly_df, entitlement, full_analysis=full_analysis, surface=surface)
    except Exception:
        log.exception("AMI assistant panel failed on %s", active_page)
        _streamlit.caption("AMI is unavailable right now.")


def _surface_css() -> str:
    """Exactly one Ask AMI per device: the phone bar below the phone breakpoint, the sidebar
    panel above it. (Both stay mounted so widget identity is stable across reruns.)"""
    try:
        from mobile_foundation import PHONE_MAX_PX
    except ImportError:
        PHONE_MAX_PX = 640
    return f"""<style>
@media (min-width: {PHONE_MAX_PX + 1}px) {{
    .st-key-{PHONE_ROOT_KEY},
    [data-testid="stLayoutWrapper"]:has(> .st-key-{PHONE_ROOT_KEY}) {{ display: none; }}
}}
@media (max-width: {PHONE_MAX_PX}px) {{
    .st-key-{SIDEBAR_ROOT_KEY} {{ display: none; }}
}}
</style>"""


def render_ami_assistant_panel(st: Any, *, active_page: str, yearly_df: Any = None, entitlement: Any = None,
                               full_analysis: FullAnalysis | None = None) -> None:
    """The one Ask AMI entry: the sidebar panel (desktop) and the top-of-page bar (phone).
    Never breaks the page: any failure shows a short notice instead.

    ``entitlement``: the page gate's own plan snapshot for this run (see
    tools.registry.entitlement_block). ``full_analysis``: the host's Command Center handoff,
    called only when the user presses Get full analysis; without it the button isn't shown."""
    try:
        with st.sidebar:
            with st.container(key=SIDEBAR_ROOT_KEY):
                _panel(active_page, yearly_df, entitlement, full_analysis, "sidebar")
    except Exception:
        log.exception("AMI assistant panel failed on %s", active_page)
        try:
            st.sidebar.caption("AMI is unavailable right now.")
        except Exception:
            pass
    try:
        with st.container(key=PHONE_ROOT_KEY):
            st.markdown(_surface_css(), unsafe_allow_html=True)
            last = st.session_state.get(LAST_KEY)
            opened = bool(st.session_state.get(PENDING_KEY)) or (isinstance(last, dict) and bool(last.get("answer")))
            with st.expander("💬 Ask AMI", expanded=opened):
                _panel(active_page, yearly_df, entitlement, full_analysis, "phone")
    except Exception:
        log.exception("AMI phone entry failed on %s", active_page)
