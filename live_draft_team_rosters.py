"""Team rosters for the Live Draft Room, the same in Solo and Shared drafts.

A collapsed "Team rosters" panel under the status strip: choose a team (the viewer's own first) and
see its picks in order, with round, pick and position, plus a one-line count for every team. It reads
only the room's ``teams`` and ``draft_board`` and never writes the room, so Shared Draft authority,
synchronization and persistence are untouched.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _name(row: dict[str, Any]) -> str:
    for key in ("fullName", "Player", "player_name", "Name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "—"


def team_rosters(room: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """{team: [{Pick, Round, Player, Pos}, ...]} in pick order, every team present (empty or not)."""
    room = room if isinstance(room, dict) else {}
    teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in teams}
    rows = [r for r in (room.get("draft_board") or []) if isinstance(r, dict)]
    for row in sorted(rows, key=lambda r: int(r.get("Pick") or 0)):
        team = str(row.get("Fantasy Team") or row.get("Team") or "").strip()
        if not team:
            continue
        out.setdefault(team, []).append({
            "Pick": row.get("Pick"),
            "Round": row.get("Round"),
            "Player": _name(row),
            "Pos": str(row.get("Primary Position") or row.get("Pos") or ""),
        })
    return out


def render_team_rosters(st: Any, room: dict[str, Any] | None, *, viewer_team: str = "", key: str = "ldr_team_rosters") -> bool:
    """Paint the panel; False when the room has no teams."""
    rosters = team_rosters(room)
    if not rosters:
        return False
    teams = list(rosters)
    viewer = str(viewer_team or "").strip()
    if viewer in teams:
        teams = [viewer] + [t for t in teams if t != viewer]
    with st.expander("Team rosters", expanded=False, icon=":material/groups:"):
        st.caption(" · ".join(f"**{t}** {len(rosters[t])}" for t in teams))
        choice = st.selectbox(
            "Team",
            teams,
            index=0,
            key=f"{key}_team",
            format_func=lambda t: f"{t} (you)" if t == viewer else t,
        )
        picks = rosters.get(choice) or []
        if not picks:
            st.caption(f"{choice} has not drafted anyone yet.")
        else:
            st.dataframe(pd.DataFrame(picks), hide_index=True, use_container_width=True)
    return True
