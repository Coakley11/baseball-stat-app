"""Portfolio demo state loaders — baseball app. Presentation only, no new models."""

from __future__ import annotations

import pandas as pd

import portfolio_polish as pp

DEMO_TEAM = "My Team"
DEMO_TEAMS = ["My Team", "Team Beta", "Team Gamma", "Team Delta"]

# Stars already off the board — leaves elite decision (e.g. Henderson vs Devers) on the table.
DEMO_DRAFT_PICKS = [
    (1, "Team Beta", "Aaron Judge"),
    (2, "Team Gamma", "Shohei Ohtani"),
    (3, "Team Delta", "Juan Soto"),
    (4, "My Team", "Mookie Betts"),
    (5, "Team Delta", "Vladimir Guerrero Jr."),
    (6, "Team Gamma", "Ronald Acuña Jr."),
    (7, "Team Beta", "Freddie Freeman"),
    (8, "My Team", "Jose Altuve"),
    (9, "Team Beta", "Yordan Alvarez"),
    (10, "Team Gamma", "Fernando Tatis Jr."),
    (11, "Team Delta", "Corey Seager"),
    (12, "My Team", "Kyle Tucker"),
]

ML_SPOTLIGHT_PLAYERS = [
    "Aaron Judge",
    "Shohei Ohtani",
    "Juan Soto",
    "Gunnar Henderson",
]

PENDING_DRAFT_WIDGET_DEFAULTS_KEY = "_pp_pending_draft_widget_defaults"
DRAFT_DEMO_FLASH_KEY = "_pp_draft_demo_flash"


def _apply_draft_board_state(st) -> None:
    """Draft room data — safe to set anytime (no Streamlit widget binding)."""
    rows = []
    for rnd in range(1, 21):
        for team in DEMO_TEAMS:
            rows.append({"Round": rnd, "Pick": len(rows) + 1, "Team": team, "Player": ""})
    table = pd.DataFrame(rows)
    for pick_no, team, player in DEMO_DRAFT_PICKS:
        if pick_no <= len(table):
            table.loc[pick_no - 1, "Team"] = team
            table.loc[pick_no - 1, "Player"] = player
    st.session_state["draft_room_table"] = table
    st.session_state["room_your_team"] = DEMO_TEAM
    st.session_state["room_team_count"] = 4
    st.session_state["room_team_names"] = "\n".join(DEMO_TEAMS)


def _apply_draft_widget_defaults(st) -> None:
    """Draft Assistant widget keys — apply only before those widgets render."""
    st.session_state["draft_assistant_synced_team"] = DEMO_TEAM
    st.session_state["draft_top_n"] = 10
    st.session_state["draft_use_ml_blend"] = True
    st.session_state["draft_ml_blend_weight"] = 0.12


def _clear_stale_draft_ui_keys(st) -> None:
    """Drop player picks that may no longer exist in the recommendation pool."""
    for key in (
        "draft_assistant_selected_player",
        "draft_assistant_breakdown_player",
        "pending_draft_assistant_player",
    ):
        st.session_state.pop(key, None)


def apply_pending_draft_demo(st) -> None:
    """Apply deferred Draft Assistant widget defaults before page widgets render."""
    if not st.session_state.pop(PENDING_DRAFT_WIDGET_DEFAULTS_KEY, False):
        return
    _apply_draft_widget_defaults(st)
    _clear_stale_draft_ui_keys(st)


def schedule_draft_demo(st) -> None:
    """Auto-load draft demo after page-state restore (Portfolio Demo Mode)."""
    if pp.demo_applied(st, "draft_assistant"):
        return
    _apply_draft_board_state(st)
    _apply_draft_widget_defaults(st)
    _clear_stale_draft_ui_keys(st)
    mark_demo_applied(st, "draft_assistant")


def request_draft_demo(st) -> None:
    """
    Load demo draft from the button after widgets may already exist.

    Board state applies immediately; widget-bound keys apply on the next rerun.
    """
    _apply_draft_board_state(st)
    st.session_state[PENDING_DRAFT_WIDGET_DEFAULTS_KEY] = True
    st.session_state[DRAFT_DEMO_FLASH_KEY] = True
    mark_demo_applied(st, "draft_assistant")


def load_portfolio_demo_draft(st) -> None:
    """Populate draft room with a realistic mid-draft board (full apply)."""
    _apply_draft_board_state(st)
    _apply_draft_widget_defaults(st)
    _clear_stale_draft_ui_keys(st)
    mark_demo_applied(st, "draft_assistant")


def draft_demo_summary(st) -> str:
    """Human-readable summary for success banner after demo load."""
    table = st.session_state.get("draft_room_table", pd.DataFrame())
    if table.empty or "Player" not in table.columns:
        return "Portfolio demo draft loaded."
    filled = table[table["Player"].astype(str).str.strip() != ""]
    team = st.session_state.get("draft_assistant_synced_team", DEMO_TEAM)
    my_count = int((filled["Team"].astype(str) == str(team)).sum())
    pick_no = len(filled) + 1
    return (
        f"Portfolio demo draft loaded — **{team}** roster: **{my_count}** players; "
        f"league on pick **#{pick_no}** (12 stars already drafted)."
    )


def load_portfolio_demo_ml(st) -> None:
    """Trigger ML pipeline and spotlight star players."""
    st.session_state["ml_predictions_have_run"] = True
    st.session_state["ml_predictions_refresh_requested"] = True
    if "ml_full_generation_requested" not in st.session_state:
        st.session_state["ml_full_generation_requested"] = True
    st.session_state["ML_FULL_GENERATION_REQUESTED_KEY"] = True
    st.session_state["ml_importance_stat"] = "HR"
    st.session_state["ml_sort_by"] = "Predicted OPS"
    st.session_state["ml_position_filter"] = "All positions"
    st.session_state["ml_projection_insight_player"] = ML_SPOTLIGHT_PLAYERS[0]
    st.session_state["_pp_demo_ml_trigger"] = True
    mark_demo_applied(st, "ml_predictions")


def load_portfolio_demo_career(st) -> None:
    st.session_state["career_sort_stat_filter"] = "HR"
    mark_demo_applied(st, "career_totals")


def mark_demo_applied(st, page_key: str) -> None:
    pp.mark_demo_applied(st, page_key)


def schedule_page_demo(st, active_page: str) -> None:
    """Auto-load curated demo after sidebar page-state restore."""
    if not pp.is_demo_mode(st):
        return
    if active_page == "Draft Assistant Simulator" and not pp.demo_applied(st, "draft_assistant"):
        schedule_draft_demo(st)
    elif active_page == "ML Predictions" and not pp.demo_applied(st, "ml_predictions"):
        load_portfolio_demo_ml(st)
    elif active_page == "Career Totals" and not pp.demo_applied(st, "career_totals"):
        load_portfolio_demo_career(st)


def render_draft_demo_button(st, active_page: str) -> None:
    if active_page != "Draft Assistant Simulator":
        return
    if st.session_state.pop(DRAFT_DEMO_FLASH_KEY, False):
        st.success(draft_demo_summary(st))
    if st.button("Load Portfolio Demo Draft", type="primary", key="pp_load_demo_draft"):
        request_draft_demo(st)
        st.rerun()
