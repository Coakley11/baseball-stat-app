"""Shared Streamlit draft button — single UI path via draft_actions."""

from __future__ import annotations

from typing import Any

from draft_actions import can_draft_player, draft_action_context, draft_button_diagnostics, draft_player


def draft_disabled_hint(reason: str) -> str:
    """Short user-facing hint when draft is not allowed."""
    text = str(reason or "").strip()
    if text.startswith("Not your pick"):
        return "Not your pick"
    return text[:80] if text else "Cannot draft"


def lookup_player_draft_meta(session: dict[str, Any], player_name: str) -> dict[str, str]:
    """Best-effort position + MLB team for queue display."""
    name = str(player_name or "").strip()
    meta = {"position": "—", "team": "—"}
    if not name:
        return meta

    def _from_row(row: dict[str, Any]) -> dict[str, str]:
        pos = str(
            row.get("Primary Position")
            or row.get("primaryPos")
            or row.get("displayPosition")
            or row.get("position")
            or "—"
        ).strip() or "—"
        team = str(
            row.get("Team")
            or row.get("teamName")
            or row.get("primaryTeamName")
            or row.get("Franchise")
            or "—"
        ).strip() or "—"
        return {"position": pos, "team": team}

    def _match_pool(pool: Any) -> dict[str, str] | None:
        if pool is None or getattr(pool, "empty", True):
            return None
        col = "fullName" if "fullName" in pool.columns else "Player"
        if col not in pool.columns:
            return None
        target = name.lower()
        for _, row in pool.iterrows():
            full = str(row.get(col) or "").strip()
            if full.lower() == target or full == name:
                return _from_row(row.to_dict())
        return None

    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        prepare_live_draft_state(session)
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            hit = _match_pool(room.get("pool"))
            if hit:
                return hit
    except Exception:
        pass

    pool_df = session.get("draft_room_player_pool")
    if pool_df is not None:
        hit = _match_pool(pool_df)
        if hit:
            return hit

    return meta


def render_draft_button(
    st: Any,
    session: dict[str, Any],
    player_name: str,
    *,
    source: str,
    key_suffix: str,
    use_sidebar: bool = False,
    column: Any = None,
    label: str = "Draft",
    button_type: str = "secondary",
    show_disabled_reason: bool = True,
    flash_key: str = "workflow_sidebar_flash",
    extra_disabled: bool = False,
    extra_disabled_reason: str = "",
) -> bool:
    """
    Render a draft button wired to draft_player().

    Returns True when a draft was attempted (caller should st.rerun()).
    """
    name = str(player_name or "").strip()
    container = column if column is not None else (st.sidebar if use_sidebar else st)
    btn_key = f"draft_btn_{source}_{key_suffix}"

    if extra_disabled:
        container.button(
            label,
            key=f"{btn_key}_blocked",
            disabled=True,
            use_container_width=True,
            type=button_type,
        )
        if show_disabled_reason and extra_disabled_reason:
            container.caption(draft_disabled_hint(extra_disabled_reason))
        return False

    allowed, reason = can_draft_player(session, name)
    if allowed:
        if container.button(label, key=btn_key, use_container_width=True, type=button_type):
            result = draft_player(session, name, source=source, st_obj=st)
            msg = str(result.get("message") or result.get("error") or "Drafted.")
            session[flash_key] = msg
            if not result.get("ok") and result.get("error") == "shared_commit_failed":
                session["_draft_room_conflict_notice"] = msg
            return True
        return False

    container.button(
        label,
        key=f"{btn_key}_disabled",
        disabled=True,
        use_container_width=True,
        type=button_type,
    )
    if show_disabled_reason:
        try:
            from draft_actions import draft_button_diagnostics

            diag = draft_button_diagnostics(session, name)
            code = str(diag.get("disable_reason") or "").strip()
            if code:
                container.caption(f"Disabled: {code}")
            elif reason:
                container.caption(draft_disabled_hint(reason))
        except ImportError:
            container.caption(draft_disabled_hint(reason))
    return False


def render_live_draft_queue_panel(st: Any, session: dict[str, Any]) -> bool:
    """
    Queue table on Live Draft Room — order, player, position, team, draft button.

    Returns True if caller should rerun.
    """
    queue = session.get("draft_queue") or []
    if not isinstance(queue, list):
        queue = []
    queue = [str(x).strip() for x in queue if str(x).strip()]

    st.subheader("Draft Queue")
    if not queue:
        st.caption("Empty — add players with **Queue player** in Player Actions.")
        return False

    ctx = draft_action_context(session)
    if ctx.get("is_your_pick") and ctx.get("current_pick"):
        st.caption(f"Your pick · Pick {ctx['current_pick']}")
    elif ctx.get("on_clock_team"):
        pick_n = ctx.get("current_pick")
        clock = f"Pick {pick_n}: {ctx['on_clock_team']}" if pick_n else str(ctx["on_clock_team"])
        st.caption(f"On the clock — {clock}")

    rerun = False
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        paused = isinstance(room, dict) and room.get("status") == "paused"
    except ImportError:
        paused = False

    header = st.columns([0.08, 0.34, 0.14, 0.22, 0.22])
    header[0].caption("**#**")
    header[1].caption("**Player**")
    header[2].caption("**Pos**")
    header[3].caption("**Team**")
    header[4].caption("**Draft**")

    for idx, pname in enumerate(queue[:20]):
        meta = lookup_player_draft_meta(session, pname)
        cols = st.columns([0.08, 0.34, 0.14, 0.22, 0.22])
        cols[0].write(f"{idx + 1}")
        cols[1].write(pname[:40] + ("…" if len(pname) > 40 else ""))
        cols[2].write(meta["position"])
        cols[3].write(meta["team"][:18] + ("…" if len(meta["team"]) > 18 else ""))
        if render_draft_button(
            st,
            session,
            pname,
            source="live_queue",
            key_suffix=f"live_queue_{idx}",
            column=cols[4],
            show_disabled_reason=idx == 0,
            extra_disabled=paused,
            extra_disabled_reason="Draft is paused — resume to pick.",
        ):
            rerun = True

    if len(queue) > 20:
        st.caption(f"+{len(queue) - 20} more in queue")
    return rerun


def render_active_draft_ownership_dev_panel(
    st: Any,
    session: dict[str, Any],
    *,
    player_name: str = "",
    developer_mode: bool = False,
) -> None:
    """Sidebar Dev Mode panel for active draft source and button gating."""
    if not developer_mode:
        return
    diag = draft_button_diagnostics(session, player_name)
    with st.sidebar.expander("Active draft ownership", expanded=True):
        for key, val in diag.items():
            if val is None or val == "":
                continue
            st.text(f"{key}: {val}")


_START_LIVE_DRAFT_TRACE_KEY = "_start_live_draft_trace"


def record_start_live_draft_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Merge Start Live Draft handler diagnostics for Dev Mode."""
    trace = dict(session.get(_START_LIVE_DRAFT_TRACE_KEY) or {})
    trace.update({k: v for k, v in fields.items() if v is not None})
    session[_START_LIVE_DRAFT_TRACE_KEY] = trace
    return trace


def mark_start_live_draft_clicked(session: dict[str, Any]) -> None:
    record_start_live_draft_diagnostics(
        session,
        start_live_draft_clicked=True,
        start_live_draft_attempted=True,
        start_live_draft_error="",
    )


_SIM_CONVERT_SETTING_KEYS = (
    ("sim_convert_live_draft_timer", "Timer per pick"),
    ("sim_convert_live_draft_proj_window", "Projection window"),
    ("sim_convert_live_draft_proj_style", "Rebalancing style"),
    ("sim_convert_live_draft_auto_rule", "Auto-pick rule"),
)


def assess_required_live_settings(session: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Return (complete, missing_labels, disabled_reason) for simulator convert panel."""
    missing: list[str] = []
    for key, label in _SIM_CONVERT_SETTING_KEYS:
        val = session.get(key)
        if val is None or str(val).strip() == "":
            missing.append(label)
    if missing:
        return False, missing, f"Missing: {', '.join(missing)}"
    return True, [], ""


def copy_sim_convert_settings_to_live(session: dict[str, Any]) -> None:
    """Copy convert-panel widget values into canonical live_draft_* keys."""
    mapping = {
        "sim_convert_live_draft_timer": "live_draft_timer",
        "sim_convert_live_draft_proj_window": "live_draft_proj_window",
        "sim_convert_live_draft_proj_style": "live_draft_proj_style",
        "sim_convert_live_draft_auto_rule": "live_draft_auto_rule",
    }
    for src, dst in mapping.items():
        if src in session:
            session[dst] = session[src]


def on_open_simulator_convert_panel() -> None:
    import streamlit as st

    record_start_live_draft_diagnostics(st.session_state, convert_simulator_clicked=True)
    st.session_state["_simulator_to_live_show_confirm"] = True


def on_cancel_simulator_convert_panel() -> None:
    import streamlit as st

    st.session_state.pop("_simulator_to_live_show_confirm", None)


def on_confirm_convert_simulator_to_live() -> None:
    import streamlit as st

    session = st.session_state
    complete, missing, reason = assess_required_live_settings(session)
    if not complete:
        record_start_live_draft_diagnostics(
            session,
            confirm_convert_clicked=False,
            required_live_settings_complete=False,
            confirm_button_disabled_reason=reason,
        )
        return
    copy_sim_convert_settings_to_live(session)
    mark_start_live_draft_clicked(session)
    record_start_live_draft_diagnostics(
        session,
        confirm_convert_clicked=True,
        required_live_settings_complete=True,
        confirm_button_disabled_reason="",
        start_live_draft_mode="simulator",
    )
    session["_start_live_draft_mode"] = "simulator"
    session["_start_live_draft_pending"] = True
    session.pop("_simulator_to_live_show_confirm", None)


def on_start_new_live_draft() -> None:
    import streamlit as st

    mark_start_live_draft_clicked(st.session_state)
    st.session_state["_start_live_draft_mode"] = "new"
    st.session_state["_start_live_draft_pending"] = True
    st.session_state.pop("_simulator_to_live_show_confirm", None)


_LIVE_DRAFT_UI_DIAG_KEY = "_live_draft_ui_diag"


def record_live_draft_ui_diagnostics(
    session: dict[str, Any],
    updates: dict[str, Any] | None = None,
    /,
    **fields: Any,
) -> dict[str, Any]:
    """Merge manual-draft UI diagnostic fields into session (accepts dict and/or kwargs)."""
    merged: dict[str, Any] = {}
    if updates:
        merged.update(updates)
    merged.update(fields)
    diag = dict(session.get(_LIVE_DRAFT_UI_DIAG_KEY) or {})
    diag.update(merged)
    session[_LIVE_DRAFT_UI_DIAG_KEY] = diag
    return diag


def render_live_manual_draft_panel(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    user_team: str = "",
    multiplayer: bool = False,
) -> bool:
    """
    Manual Draft selectbox + Draft Player button on Live Draft Room.

    Returns True when caller should rerun.
    """
    from draft_actions import draft_action_context

    ctx = draft_action_context(session)
    render_path = "live_draft_room"
    diag_base = {
        "render_path": render_path,
        "draft_button_should_render": bool(
            ctx.get("draft_enabled")
            and ctx.get("is_your_pick")
            and str(ctx.get("draft_status") or "") == "in_progress"
        ),
        "draft_button_rendered": False,
        "player_action_panel_rendered": True,
        "selected_player": "",
        "draft_action_disable_reason": "",
        "multiplayer_mode": multiplayer,
    }

    try:
        from live_draft_state import live_draft_get_available

        try:
            available = live_draft_get_available(room)
        except Exception:
            available = None
    except ImportError:
        available = None

    available_count = int(len(available)) if available is not None and hasattr(available, "__len__") else 0
    diag_base["available_player_count"] = available_count

    st.subheader("Manual Draft")
    if available is None:
        record_live_draft_ui_diagnostics(
            session,
            {
                **diag_base,
                "filtered_player_count": 0,
                "draft_button_rendered": False,
                "draft_action_disable_reason": "pool_unavailable",
            },
        )
        return False
    if available_count == 0:
        record_live_draft_ui_diagnostics(
            session,
            {
                **diag_base,
                "filtered_player_count": 0,
                "draft_button_rendered": False,
                "draft_action_disable_reason": "empty_pool",
            },
        )
        st.warning("No players left in the pool.")
        return False

    all_player_options = available.sort_values(
        ["Expected Fantasy Value", "Model Rank"], ascending=[False, True]
    )["fullName"].astype(str).tolist()
    try:
        from draft_source_validation import allow_free_pool_drafting, allowed_draft_player_names

        if allow_free_pool_drafting(session, live_room=room):
            player_options = all_player_options
        else:
            player_options = allowed_draft_player_names(
                session,
                live_room=room,
                available_names=all_player_options,
            )
    except ImportError:
        player_options = all_player_options

    filtered_count = len(player_options)
    diag_base["filtered_player_count"] = filtered_count
    paused = room.get("status") == "paused"

    if not player_options:
        record_live_draft_ui_diagnostics(
            session,
            {
                **diag_base,
                "draft_button_rendered": False,
                "draft_action_disable_reason": "no_allowed_players",
            },
        )
        st.info(
            "Add players to your **Queue**, **Watchlist**, or **Tracked Players** "
            "to draft — or enable free pool drafting in the shared room panel."
        )
        if diag_base["draft_button_should_render"]:
            st.button(
                "Draft Player",
                key="live_draft_player_select_blocked",
                disabled=True,
                type="primary",
                help="No eligible players in your queue, watchlist, or tracked list.",
            )
            record_live_draft_ui_diagnostics(session, draft_button_rendered=True)
        return False

    selected_player = st.selectbox(
        "Draft candidate",
        player_options,
        key="live_draft_player_select",
        help="Draft from your queue, watchlist, tracked players, or the full pool when enabled.",
    )
    diag_base["selected_player"] = str(selected_player or "")

    allowed, disable_reason = can_draft_player(session, str(selected_player or ""))
    if not allowed:
        diag_base["draft_action_disable_reason"] = disable_reason

    if render_draft_button(
        st,
        session,
        selected_player,
        source="live_draft_room",
        key_suffix="live_manual",
        label="Draft Player",
        button_type="primary",
        extra_disabled=paused,
        extra_disabled_reason="Draft is paused — resume to pick.",
    ):
        record_live_draft_ui_diagnostics(session, {**diag_base, "draft_button_rendered": True})
        return True

    record_live_draft_ui_diagnostics(
        session,
        {
            **diag_base,
            "draft_button_rendered": True,
            "draft_action_disable_reason": disable_reason if not allowed else "",
        },
    )
    return False


def render_start_live_draft_dev_panel(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    trace = dict(session.get(_START_LIVE_DRAFT_TRACE_KEY) or {})
    keys = (
        "convert_simulator_clicked",
        "convert_confirmation_rendered",
        "confirm_button_rendered",
        "required_live_settings_complete",
        "confirm_button_disabled_reason",
        "confirm_convert_clicked",
        "start_live_draft_clicked",
        "start_live_draft_attempted",
        "start_live_draft_error",
        "simulator_board_pick_count_before_start",
        "simulator_board_source",
        "live_room_created",
        "replayed_pick_count",
        "promote_skipped_count",
        "live_draft_status_after_start",
        "live_user_team_after_start",
        "active_draft_source_after_start",
        "current_pick_after_start",
        "promote_error",
        "pool_live_count",
        "start_live_draft_mode",
    )
    with st.expander("Start Live Draft trace (Dev Mode)", expanded=True):
        for key in keys:
            val = trace.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
        if trace.get("start_live_draft_clicked") and not trace.get("live_room_created"):
            st.warning("Start Live Draft was clicked but no live room was created — see start_live_draft_error / promote_error.")
