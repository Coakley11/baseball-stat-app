"""
Apply Command Center deep-link query params when a suite app opens.

Call once near the top of each Streamlit entry file (after set_page_config).
Music apps must also call ``finalize_suite_resume_launch`` after the song catalog loads.
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


def finalize_suite_resume_launch(
    st: Any,
    app_key: str,
    *,
    song_picker_catalog: dict | None = None,
    song_library: dict | None = None,
) -> bool:
    """
    Apply deferred resume state after app bootstrap (catalog loaded).

    ``apply_suite_resume_launch`` only seeds query params early; this commits
    the song selection via ``apply_pick_key`` so defaults do not override Continue.
    """
    key = str(app_key or "").strip()
    if key == "math":
        key = "applied_intelligence"
    launch_flag = f"_suite_resume_launch_{key}"
    done_flag = f"_suite_resume_finalized_{key}"
    if not st.session_state.get(launch_flag) or st.session_state.get(done_flag):
        return False

    if key == "music" and song_picker_catalog:
        _finalize_music_resume(st, song_picker_catalog, song_library)

    st.session_state[done_flag] = True
    return True


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
        _apply_baseball(st, resume, page)
    elif key == "nba":
        _apply_nba(st, resume, page)
    elif key == "investment":
        _apply_investment(st, resume, page)
    elif key == "future_lens":
        _apply_future_lens(st, resume, page)
    elif key == "applied_intelligence":
        _apply_applied_intelligence(st, page)

    st.session_state[flag] = True
    return True


def _finalize_music_resume(
    st: Any,
    song_picker_catalog: dict,
    song_library: dict | None,
) -> None:
    pick = str(st.session_state.get("active_catalog_pick_key") or _qp_get(st, "suite_pick_key")).strip()
    resume = _qp_get(st, "suite_resume")
    if not pick and resume.startswith(("song:", "backing:")):
        pick = resume.split(":", 1)[-1].strip()
    if pick:
        try:
            from songs.state import apply_pick_key

            apply_pick_key(
                st,
                pick,
                song_picker_catalog,
                song_library=song_library,
                skip_activity_log=True,
            )
        except Exception:
            pass

    display_key = _qp_get(st, "suite_display_key")
    if display_key:
        try:
            from songs.key_state import PENDING_DISPLAY_KEY

            st.session_state[PENDING_DISPLAY_KEY] = display_key
        except Exception:
            st.session_state["display_key"] = display_key

    instrument = _qp_get(st, "suite_instrument")
    if instrument:
        try:
            from practice_setup_globals import set_active_instrument

            set_active_instrument(st.session_state, instrument)
        except Exception:
            st.session_state["instrument"] = instrument


def _apply_music(st: Any, resume: str, page: str) -> None:
    pick = _qp_get(st, "suite_pick_key")
    song = _qp_get(st, "suite_song")
    display_key = _qp_get(st, "suite_display_key")
    instrument = _qp_get(st, "suite_instrument")
    if pick:
        st.session_state["active_catalog_pick_key"] = pick
    if song:
        st.session_state["song"] = song
    if resume.startswith("song:") and not pick:
        st.session_state["active_catalog_pick_key"] = resume.split(":", 1)[-1].strip()
    if resume.startswith("backing:") and not pick:
        st.session_state["active_catalog_pick_key"] = resume.split(":", 1)[-1].strip()
    if display_key:
        try:
            from songs.key_state import PENDING_DISPLAY_KEY

            st.session_state[PENDING_DISPLAY_KEY] = display_key
        except Exception:
            st.session_state["display_key"] = display_key
    if instrument:
        try:
            from practice_setup_globals import set_active_instrument

            set_active_instrument(st.session_state, instrument)
        except Exception:
            st.session_state["instrument"] = instrument
    section = _qp_get(st, "suite_section_focus")
    if section:
        st.session_state["practice_focus_section"] = section
    target = page.strip()
    if not target:
        target = "backing" if resume.startswith("backing:") else "practice"
    if target.lower() in {"practice log", "practice studio"}:
        target = "practice"
    elif target.lower() == "backing track studio":
        target = "backing"
    try:
        from studio_page_state import navigate_studio_page

        navigate_studio_page(st.session_state, target)
    except Exception:
        st.session_state["studio_page"] = target


def _apply_baseball(st: Any, resume: str, page: str) -> None:
    pa = _qp_get(st, "suite_player_a")
    pb = _qp_get(st, "suite_player_b")
    if not pa and resume.startswith("compare:"):
        parts = resume.split(":", 2)
        if len(parts) >= 3:
            pa, pb = parts[1].strip(), parts[2].strip()
    if pa and pb:
        st.session_state["pending_sig_player_a"] = pa
        st.session_state["pending_sig_player_b"] = pb
        st.session_state["pending_compare_players"] = [pa, pb]
    elif pa:
        st.session_state["pending_sig_player_a"] = pa
        st.session_state["pending_compare_players"] = [pa]
    target_page = page.strip()
    if not target_page and resume.startswith("compare:"):
        target_page = "Comparison Tool"
    if not target_page and resume.startswith("trend:"):
        target_page = "Trend Value"
    trend_player = _qp_get(st, "suite_trend_player")
    if not trend_player and resume.startswith("trend:"):
        trend_player = resume.split(":", 1)[-1].strip()
    if trend_player:
        st.session_state["single_trend_dashboard_player"] = trend_player
        st.session_state["pending_trend_player"] = trend_player
    if target_page:
        st.session_state["_navigate_to_page"] = target_page


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


def _apply_investment(st: Any, resume: str, page: str) -> None:
    target = page.strip()
    if not target and resume:
        if "health" in resume.lower():
            target = "Portfolio Health"
        elif "scenario" in resume.lower():
            target = "Efficient Frontier"
        elif "main" in resume.lower():
            target = "Portfolio Inputs"
    if target:
        st.session_state["_suite_investment_page"] = target
    hfp = _qp_get(st, "suite_holdings_fp")
    if hfp:
        st.session_state["_suite_holdings_fp"] = hfp


def _apply_future_lens(st: Any, resume: str, page: str) -> None:
    sim = _qp_get(st, "suite_sim")
    if sim:
        st.session_state["_suite_fl_sim"] = sim
        if not st.session_state.get("specific_skill"):
            st.session_state["specific_skill"] = sim
    if resume.startswith("sim:") and not sim:
        st.session_state["_suite_fl_sim"] = resume.split(":", 1)[-1].strip()
    if resume.startswith("career:") and not sim:
        st.session_state["_suite_fl_sim"] = resume.split(":", 1)[-1].strip()
    domain = _qp_get(st, "suite_fl_domain")
    if domain:
        st.session_state["broad_domain"] = domain
    area = _qp_get(st, "suite_fl_area")
    if area:
        st.session_state["area"] = area
    timeline_year = _qp_get(st, "suite_fl_timeline_year")
    if timeline_year:
        try:
            st.session_state["timeline_year"] = int(timeline_year)
        except ValueError:
            st.session_state["timeline_year"] = timeline_year
    sim_year = _qp_get(st, "suite_fl_sim_year")
    if sim_year:
        try:
            st.session_state["sim_year"] = int(sim_year)
        except ValueError:
            pass
    fl_view = _qp_get(st, "suite_fl_view")
    if fl_view:
        st.session_state["_suite_fl_view"] = fl_view
    elif page == "timeline":
        st.session_state["_suite_fl_view"] = "timeline"
    elif page == "skills":
        st.session_state["_suite_fl_view"] = "skills"
    elif page:
        st.session_state["_suite_fl_view"] = "simulation"
    if domain and area:
        st.session_state["future_project"] = f"{domain} / {area}"


def _apply_applied_intelligence(st: Any, page: str) -> None:
    lesson = _qp_get(st, "suite_lesson")
    if lesson:
        st.session_state["_suite_ai_lesson"] = lesson
    if page:
        st.session_state["_suite_ai_page"] = page
    try:
        from suite_analytical_question import hydrate_applied_intelligence_session

        hydrate_applied_intelligence_session(st)
    except Exception:
        q = _qp_get(st, "suite_ai_question")
        if q:
            st.session_state["_suite_ai_question"] = q
            st.session_state["ps_library_problem"] = q
        ctx_raw = _qp_get(st, "suite_ai_context")
        if ctx_raw:
            st.session_state["_suite_ai_context"] = ctx_raw
        for qp, key in (
            ("suite_ai_source_app", "_suite_ai_source_app"),
            ("suite_ai_source_page", "_suite_ai_source_page"),
            ("suite_ai_area", "_suite_ai_area"),
            ("suite_ai_question_id", "_suite_ai_question_id"),
        ):
            val = _qp_get(st, qp)
            if val:
                st.session_state[key] = val
