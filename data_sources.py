"""Baseball data sources the app uses, and the attribution shown for them.

Source credits only — the app is independent of every source listed here. Lahman details
come from the readme of the bundled release ("The SABR Lahman Baseball Database
1871-2025", section 0.1 Copyright Notice & Limited Use License).
"""

from __future__ import annotations

from typing import Any

LAHMAN_VERSION = "Version 2025 (1871–2025 seasons)"
LAHMAN_TABLES = ("People", "Batting", "Fielding", "HallOfFame", "AwardsPlayers")
LAHMAN_URL = "https://sabr.org/lahman-database/"
LAHMAN_LICENSE = "Creative Commons Attribution-ShareAlike 3.0 Unported"
LAHMAN_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"

SHORT_CREDIT = "Baseball data: Lahman Baseball Database — Sean Lahman / SABR"

NOT_AFFILIATED = (
    "Credits identify data sources only. This app is independent and is not affiliated with, "
    "endorsed by or licensed by MLB, SABR, Sean Lahman, Seamheads or FantasyPros."
)


def about_data_markdown() -> str:
    """Body of the "About data & sources" section."""
    return "\n\n".join(
        [
            "**Historical statistics** — The SABR Lahman Baseball Database, "
            f"{LAHMAN_VERSION}. Created by Sean Lahman; copyright 1996–2025 SABR. "
            "Annual updates by Bryan Walko. "
            f"Licensed under [{LAHMAN_LICENSE}]({LAHMAN_LICENSE_URL}). "
            f"Source: [sabr.org/lahman-database]({LAHMAN_URL}). "
            f"Tables used: {', '.join(LAHMAN_TABLES)}. Figures shown here are adapted "
            "(filtered, aggregated and combined) from these tables.",
            "**Negro Leagues statistics** — included in the Lahman database release above; "
            "the data was compiled by [Seamheads](https://www.seamheads.com/) and is "
            "distributed by SABR.",
            "**Current-season statistics and player photos** — MLB Stats API and MLB.com "
            "headshots, where a page shows them (for example Fantasy Standings and player "
            "cards). © MLB Advanced Media.",
            "**Fantasy market rankings** — FantasyPros 2026 expert rankings and ADP.",
            NOT_AFFILIATED,
        ]
    )


def render_data_attribution(st: Any) -> None:
    """One-line credit plus a collapsed "About data & sources" section (sidebar)."""
    st.sidebar.caption(SHORT_CREDIT)
    with st.sidebar.expander("About data & sources", expanded=False):
        st.markdown(about_data_markdown())
