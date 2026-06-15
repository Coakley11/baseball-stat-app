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
