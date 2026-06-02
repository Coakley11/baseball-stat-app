"""
Apply Command Center deep-link query params when a suite app opens.

Call once near the top of each Streamlit entry file (after set_page_config).
"""

from __future__ import annotations

from typing import Any


def _qp_get(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def apply_suite_resume_launch(st: Any, app_key: str) -> bool:
    """
    Map ?suite_resume= & ?suite_page= into session state (once per session).
    Returns True when query params were applied.
    """
    flag = f"_suite_resume_launch_{app_key}"
    if st.session_state.get(flag):
        return False

    resume = _qp_get(st, "suite_resume")
    page = _qp_get(st, "suite_page")
    if not resume and not page:
        return False

    key = str(app_key or "").strip()
    if key == "math":
        key = "applied_intelligence"

    if key == "music":
        _apply_music(st, resume, page)
    elif key == "baseball":
        _apply_baseball(st, page)
    elif key == "nba":
        _apply_nba(st, resume, page)
    elif key == "investment":
        _apply_investment(st, page)
    elif key == "future_lens":
        _apply_future_lens(st, resume, page)
    elif key == "applied_intelligence":
        _apply_applied_intelligence(st, page)

    st.session_state[flag] = True
    return True


def _apply_music(st: Any, resume: str, page: str) -> None:
    pick = _qp_get(st, "suite_pick_key")
    song = _qp_get(st, "suite_song")
    if pick:
        st.session_state["active_catalog_pick_key"] = pick
    if song:
        st.session_state["song"] = song
    if resume.startswith("song:") and not pick:
        st.session_state["active_catalog_pick_key"] = resume.split(":", 1)[-1].strip()
    target = page or ("backing" if resume.startswith("backing:") else "practice")
    try:
        from studio_page_state import navigate_studio_page

        navigate_studio_page(st.session_state, target)
    except Exception:
        st.session_state["studio_page"] = target


def _apply_baseball(st: Any, page: str) -> None:
    if not page:
        return
    st.session_state["_navigate_to_page"] = page


def _apply_nba(st: Any, resume: str, page: str) -> None:
    team = _qp_get(st, "suite_team")
    if team:
        st.session_state["_nba_restore_team"] = team
    label = page.strip()
    if not label and resume:
        if resume.startswith("nba:injury:"):
            label = "🧠 Matchup Intelligence"
        elif resume.startswith("nba:matchup:"):
            label = "🧠 Matchup Intelligence"
        elif resume.startswith("nba:playoff:"):
            label = "🏆 Playoff Bracket"
        elif resume.startswith("nba:game:"):
            label = "🔴 Live Game Center"
    if label:
        st.session_state["page_override"] = label


def _apply_investment(st: Any, page: str) -> None:
    if page:
        st.session_state["_suite_investment_page"] = page


def _apply_future_lens(st: Any, resume: str, page: str) -> None:
    sim = _qp_get(st, "suite_sim")
    if sim:
        st.session_state["_suite_fl_sim"] = sim
    if resume.startswith("sim:") and not sim:
        st.session_state["_suite_fl_sim"] = resume.split(":", 1)[-1].strip()
    if page == "timeline":
        st.session_state["_suite_fl_view"] = "timeline"
    elif page == "skills":
        st.session_state["_suite_fl_view"] = "skills"
    else:
        st.session_state["_suite_fl_view"] = "simulation"


def _apply_applied_intelligence(st: Any, page: str) -> None:
    lesson = _qp_get(st, "suite_lesson")
    if lesson:
        st.session_state["_suite_ai_lesson"] = lesson
    if page:
        st.session_state["_suite_ai_page"] = page
