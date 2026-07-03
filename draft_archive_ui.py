"""Shared UI for saved draft teams — load, save, browse."""

from __future__ import annotations

from typing import Any, Callable

from draft_archive_state import (
    activate_draft_archive,
    active_archive_label,
    clear_active_draft_archive,
    get_active_draft_archive,
    list_draft_archives,
    save_live_draft_team_archive,
    save_simulator_team_archive,
    set_active_draft_archive,
)


def _archive_options(session: dict[str, Any]) -> list[tuple[str, str]]:
    opts: list[tuple[str, str]] = []
    for entry in list_draft_archives(session):
        draft_id = str(entry.get("draft_id") or "").strip()
        if not draft_id:
            continue
        label = active_archive_label(entry)
        player_n = len(entry.get("players") or [])
        opts.append((f"{label} ({player_n} players)", draft_id))
    return opts


def render_load_saved_draft_team(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "saved_draft",
    on_loaded: Callable[[dict[str, Any] | None], None] | None = None,
) -> dict[str, Any] | None:
    """Selector: load a saved draft team for Standings / Lineup analysis."""
    archives = list_draft_archives(session)
    active = get_active_draft_archive(session)
    with st.expander("Load Saved Draft / Team", expanded=bool(active)):
        if not archives:
            st.caption("No saved draft teams yet. Finish a Live Draft or Simulator draft and use **Save Draft Team**.")
            return active
        if active:
            st.info(f"**Loaded:** {active_archive_label(active)}")
        options = _archive_options(session)
        labels = [label for label, _ in options]
        ids = [draft_id for _, draft_id in options]
        default_idx = 0
        if active:
            active_id = str(active.get("draft_id") or "")
            if active_id in ids:
                default_idx = ids.index(active_id)
        pick_label = st.selectbox(
            "Saved draft team",
            labels,
            index=default_idx,
            key=f"{key_prefix}_select",
        )
        pick_id = ids[labels.index(pick_label)] if pick_label in labels else ""
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Load team", key=f"{key_prefix}_load_btn", type="primary"):
                loaded = activate_draft_archive(session, pick_id)
                if loaded and on_loaded:
                    on_loaded(loaded)
                if loaded:
                    st.success(f"Loaded **{active_archive_label(loaded)}** for analysis.")
                    st.rerun()
        with c2:
            if active and st.button("Clear loaded draft", key=f"{key_prefix}_clear_btn"):
                clear_active_draft_archive(session)
                if on_loaded:
                    on_loaded(None)
                st.rerun()
    return get_active_draft_archive(session)


def _persist_archive(session: dict[str, Any], st: Any, *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except Exception:
        pass


def render_save_live_draft_team(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str = "live_draft_archive",
) -> None:
    cfg = dict(room.get("config") or {})
    if not team_name or team_name == "—":
        return
    with st.expander("Save completed draft team", expanded=False):
        draft_name = st.text_input(
            "Draft name",
            value=f"{cfg.get('league_name', 'Live Draft')} — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        if st.button("Save Draft Team", key=f"{key_prefix}_save_btn", type="secondary"):
            try:
                entry = save_live_draft_team_archive(
                    session,
                    room,
                    team_name=team_name,
                    draft_name=draft_name,
                )
                set_active_draft_archive(session, str(entry.get("draft_id") or ""))
                _persist_archive(session, st, reason="live_draft_archive_saved")
                st.success(
                    f"Saved **{entry.get('draft_name')}** ({len(entry.get('players') or [])} players). "
                    "Load it in **Fantasy Standings Tracker** or **Lineup Assistant**."
                )
            except Exception as exc:
                st.error(f"Could not save draft team: {exc}")


def render_save_simulator_draft_team(
    st: Any,
    session: dict[str, Any],
    board_df: Any,
    *,
    team_name: str,
    key_prefix: str = "sim_draft_archive",
) -> None:
    if not team_name or team_name == "—":
        return
    with st.expander("Save draft team for Standings / Lineup", expanded=False):
        st.caption("Save your team's roster from this mock draft without replacing the live board.")
        draft_name = st.text_input(
            "Draft name",
            value=f"Simulator — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        if st.button("Save Draft Team", key=f"{key_prefix}_save_btn", type="secondary"):
            try:
                entry = save_simulator_team_archive(
                    session,
                    board_df,
                    team_name=team_name,
                    draft_name=draft_name,
                    config=dict(session.get("draft_shared_settings") or {}),
                )
                set_active_draft_archive(session, str(entry.get("draft_id") or ""))
                _persist_archive(session, st, reason="simulator_draft_archive_saved")
                st.success(
                    f"Saved **{entry.get('draft_name')}** ({len(entry.get('players') or [])} players)."
                )
            except Exception as exc:
                st.error(f"Could not save draft team: {exc}")
