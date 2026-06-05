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


def load_portfolio_demo_draft(st) -> None:
    """Populate draft room with a realistic mid-draft board."""
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
    st.session_state["draft_assistant_synced_team"] = DEMO_TEAM
    st.session_state["room_team_count"] = 4
    st.session_state["room_team_names"] = "\n".join(DEMO_TEAMS)
    st.session_state["draft_top_n"] = 10
    st.session_state["draft_use_ml_blend"] = True
    st.session_state["draft_ml_blend_weight"] = 0.12
    mark_demo_applied(st, "draft_assistant")


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


def apply_page_demo(st, active_page: str) -> None:
    if not pp.is_demo_mode(st):
        return
    if active_page == "Draft Assistant Simulator" and not pp.demo_applied(st, "draft_assistant"):
        load_portfolio_demo_draft(st)
    elif active_page == "ML Predictions" and not pp.demo_applied(st, "ml_predictions"):
        load_portfolio_demo_ml(st)
    elif active_page == "Career Totals" and not pp.demo_applied(st, "career_totals"):
        load_portfolio_demo_career(st)


def render_draft_demo_button(st, active_page: str) -> None:
    if active_page != "Draft Assistant Simulator":
        return
    if st.button("Load Portfolio Demo Draft", type="primary", key="pp_load_demo_draft"):
        load_portfolio_demo_draft(st)
        st.rerun()
